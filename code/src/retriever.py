import ast
import hashlib
import os
import re
import uuid
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi


class CodebaseRetriever:
    """Retrieve relevant Python code using Dense + BM25 + RRF."""

    SKIP_DIRS = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".tox",
        "node_modules",
    }

    BATCH_SIZE = 100

    def __init__(
        self,
        repo_path: Path,
        persist_dir: str = None
    ):
        self.repo_path = Path(repo_path).expanduser().resolve()

        if not self.repo_path.is_dir():
            raise ValueError(
                f"Repository directory does not exist: {self.repo_path}"
            )

        self._persistent = persist_dir is not None
        self._closed = False

        # 1. Configure ChromaDB
        if self._persistent:
            self.client = chromadb.PersistentClient(
                path=str(Path(persist_dir).expanduser().resolve())
            )

            # Different repositories must not share a collection.
            repo_hash = hashlib.sha256(
                str(self.repo_path).encode()
            ).hexdigest()[:20]

            self.collection_name = f"codebase_{repo_hash}"

        else:
            # Fresh collection for each temporary review.
            self.client = chromadb.EphemeralClient()

            self.collection_name = (
                f"codebase_{uuid.uuid4().hex[:24]}"
            )

        # 2. Sentence Transformer embedding function
        self.ef = (
            embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
        )

        # 3. Create or load collection
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.ef
        )

        # 4. Local retrieval state
        self.chunks = []
        self.bm25 = None

        try:
            self._load_or_index()
        except Exception:
            self.close()
            raise

    def _python_files(self) -> list[Path]:
        """Find Python files without scanning ignored directories."""
        python_files = []

        for root, dirs, files in os.walk(self.repo_path):
            # Prevent os.walk from entering ignored directories.
            dirs[:] = sorted(
                d for d in dirs
                if d not in self.SKIP_DIRS
            )

            for filename in sorted(files):
                if not filename.endswith(".py"):
                    continue

                path = Path(root) / filename

                # Avoid indexing symlinks pointing outside the repo.
                if path.is_symlink():
                    continue

                python_files.append(path)

        return sorted(python_files)

    def _repo_fingerprint(self, files: list[Path]) -> str:
        """Hash repository Python files to detect code changes."""
        digest = hashlib.sha256()

        for file_path in files:
            relative_path = file_path.relative_to(self.repo_path)

            digest.update(str(relative_path).encode("utf-8"))

            # Read in blocks to avoid loading large files at once.
            with file_path.open("rb") as file:
                while True:
                    block = file.read(65536)

                    if not block:
                        break

                    digest.update(block)

        return digest.hexdigest()

    def _chunk_python_file(self, file_path: Path) -> list[dict]:
        """Split Python code into functions, classes and methods."""
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)

        except (SyntaxError, UnicodeDecodeError, OSError) as e:
            print(f"Skipping {file_path}: {e}")
            return []

        chunks = []
        lines = source.splitlines()

        # Keep file paths relative to the repository.
        relative_file = file_path.relative_to(
            self.repo_path
        ).as_posix()

        for node in ast.walk(tree):
            if not isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue

            # Include decorators in the extracted code.
            decorator_lines = [
                decorator.lineno
                for decorator in node.decorator_list
            ]

            start_line = min(
                [node.lineno] + decorator_lines
            )

            end_line = node.end_lineno

            if end_line is None:
                continue

            chunk_code = "\n".join(
                lines[start_line - 1:end_line]
            )

            # Unique even when different files have same-named functions.
            chunk_id = (
                f"{relative_file}:"
                f"{type(node).__name__}:"
                f"{node.name}:"
                f"{node.lineno}"
            )

            chunks.append({
                "id": chunk_id,
                "code": chunk_code,
                "name": node.name,
                "type": type(node).__name__,
                "file": relative_file,
                "start_line": start_line,
                "end_line": end_line,
            })

        return chunks

    def _load_existing_chunks(self):
        """Load documents and their IDs from a persistent collection."""
        self.chunks = []

        total = self.collection.count()

        for offset in range(0, total, self.BATCH_SIZE):
            result = self.collection.get(
                limit=self.BATCH_SIZE,
                offset=offset,
                include=["documents", "metadatas"]
            )

            for doc_id, doc, meta in zip(
                result["ids"],
                result["documents"],
                result["metadatas"]
            ):
                self.chunks.append({
                    "id": doc_id,
                    "code": doc,
                    "name": meta["name"],
                    "type": meta.get("type", "FunctionDef"),
                    "file": meta["file"],
                    "start_line": meta["start_line"],
                    "end_line": meta.get(
                        "end_line",
                        meta["start_line"]
                    ),
                })

    def _load_or_index(self):
        """Load a current index or rebuild it when code changes."""
        python_files = self._python_files()

        # Persistent indexes must be invalidated when source changes.
        fingerprint = (
            self._repo_fingerprint(python_files)
            if self._persistent
            else None
        )

        existing_metadata = self.collection.metadata or {}

        if (
            self._persistent
            and self.collection.count() > 0
            and existing_metadata.get("fingerprint") == fingerprint
            and existing_metadata.get("index_version") == 2
        ):
            print("Loading existing ChromaDB index...")
            self._load_existing_chunks()

        else:
            print("Building fresh codebase index...")

            if self._persistent:
                # Delete outdated persistent collection.
                self.client.delete_collection(
                    name=self.collection_name
                )

                self.collection = self.client.create_collection(
                    name=self.collection_name,
                    embedding_function=self.ef,
                    metadata={
                        "fingerprint": fingerprint,
                        "index_version": 2,
                    }
                )

            self.chunks = []

            for py_file in python_files:
                self.chunks.extend(
                    self._chunk_python_file(py_file)
                )

            print(f"Indexed {len(self.chunks)} code chunks")

            if self.chunks:
                # Respect Chroma's maximum supported batch size.
                max_batch_size = self.client.get_max_batch_size()
                batch_size = min(
                    self.BATCH_SIZE,
                    max_batch_size
                )

                for start in range(
                    0,
                    len(self.chunks),
                    batch_size
                ):
                    batch = self.chunks[
                        start:start + batch_size
                    ]

                    self.collection.add(
                        ids=[c["id"] for c in batch],
                        documents=[c["code"] for c in batch],
                        metadatas=[
                            {
                                "name": c["name"],
                                "type": c["type"],
                                "file": c["file"],
                                "start_line": c["start_line"],
                                "end_line": c["end_line"],
                            }
                            for c in batch
                        ],
                    )

        # Build BM25 from the same chunks as dense search.
        if self.chunks:
            tokenized = [
                self._tokenize(c["code"])
                for c in self.chunks
            ]

            self.bm25 = BM25Okapi(tokenized)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Convert text into lowercase tokens for BM25."""
        return re.findall(r"\w+", text.lower())

    def retrieve(
        self,
        query: str,
        k: int = 3,
        alpha: float = 0.5,
        max_distance: float | None = 0.7
    ) -> list[dict]:
        """Hybrid retrieval with Dense, BM25 and RRF."""

        if self._closed:
            raise RuntimeError("Retriever is already closed")

        if not self.chunks or not query.strip() or k <= 0:
            return []

        if not 0 <= alpha <= 1:
            raise ValueError("alpha must be between 0 and 1")

        # --------------------------------------------
        # 1. Dense vector search
        # --------------------------------------------
        dense = self.collection.query(
            query_texts=[query],
            n_results=min(20, len(self.chunks)),
            include=["distances"]
        )

        dense_ids = []

        for doc_id, distance in zip(
            dense["ids"][0],
            dense["distances"][0]
        ):
            if (
                max_distance is None
                or distance <= max_distance
            ):
                dense_ids.append(doc_id)

        # --------------------------------------------
        # 2. BM25 keyword search
        # --------------------------------------------
        bm25_scores = self.bm25.get_scores(
            self._tokenize(query)
        )

        # Ignore results with nonpositive BM25 scores.
        bm25_ranked = sorted(
            [
                i for i, score in enumerate(bm25_scores)
                if score > 0
            ],
            key=lambda i: bm25_scores[i],
            reverse=True
        )

        bm25_ids = [
            self.chunks[i]["id"]
            for i in bm25_ranked[:20]
        ]

        # --------------------------------------------
        # 3. Reciprocal Rank Fusion
        # --------------------------------------------
        # alpha = 0.5 gives equal weight to both searches.
        # k=60 is the RRF smoothing constant.
        rrf_scores = {}

        for rank, doc_id in enumerate(dense_ids, start=1):
            rrf_scores[doc_id] = (
                rrf_scores.get(doc_id, 0)
                + alpha / (60 + rank)
            )

        for rank, doc_id in enumerate(bm25_ids, start=1):
            rrf_scores[doc_id] = (
                rrf_scores.get(doc_id, 0)
                + (1 - alpha) / (60 + rank)
            )

        # Highest fused score first.
        ranked_ids = sorted(
            rrf_scores,
            key=lambda doc_id: (
                -rrf_scores[doc_id],
                doc_id
            )
        )

        # --------------------------------------------
        # 4. Return actual matching chunks
        # --------------------------------------------
        id_to_chunk = {
            c["id"]: c
            for c in self.chunks
        }

        return [
            id_to_chunk[doc_id]
            for doc_id in ranked_ids[:k]
            if doc_id in id_to_chunk
        ]

    def close(self):
        """Delete temporary Chroma collection after reviewing."""
        if self._closed:
            return

        self._closed = True

        try:
            if not self._persistent:
                self.client.delete_collection(
                    name=self.collection_name
                )
        finally:
            self.chunks.clear()
            self.bm25 = None

    def __enter__(self):
        """Allow use with a Python with statement."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False
