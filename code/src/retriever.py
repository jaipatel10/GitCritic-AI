from pathlib import Path
import ast
import re
import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi

class CodebaseRetriever:
    def __init__(self, repo_path: Path, persist_dir: str='./chroma_db'):
        self.repo_path = repo_path
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name='all-MiniLM-L6-v2'
        )
        self.collection = self.client.get_or_create_collection(
            name=f'codebase_{repo_path.name}',
            embedding_function=self.ef
        )
        self.chunks=[] # For BM25
        self.bm25 = None
        self._load_or_index()

    def _chunk_python_file(self, file_path: Path):
        try:
            source = file_path.read_text(encoding='utf-8')
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            return []

        chunks=[]
        lines = source.split('\n')

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                start = node.lineno - 1
                end = node.end_lineno
                chunk_code = '\n'.join(lines[start:end])

                chunks.append({
                    'code' : chunk_code,
                    'name' : node.name,
                    'type' : type(node).__name__,
                    'file' : str(file_path),
                    'start_line' : node.lineno,
                    'end_line' : end
                })
        return chunks

    def _load_or_index(self):
        """Index codebase if collection is empty otherwise load existing"""
        if self.collection.count() > 0 :
            all_docs = self.collection.get()
            self.chunks = [
                {'code': doc, 'name' : meta['name'], 'file':meta['file'], 
                'start_line': meta['start_line']}
                for doc, meta in zip(all_docs['documents'], all_docs['metadatas'])
            ]
        else:
            # Fresh index
            skip_dirs = {'.git', '__pycache__', '.venv', 'venv'}
            for py_file in self.repo_path.rglob('*.py'):
                if any(part in skip_dirs for part in py_file.parts):
                    continue
                self.chunks.extend(self._chunk_python_file(py_file))
            
            # Add to chroma
            if self.chunks:
                self.collection.add(
                    documents=[c['code'] for c in self.chunks],
                    metadatas=[{'name':c['name'], 'file': c['file'], 'start_line':c['start_line']} for c in self.chunks],
                    ids=[f'{c['file']}:{c['name']}:{c['start_line']}' for c in self.chunks] 
                )

        #Build bm25
        if self.chunks:
            tokenized = [self._tokenize(c['code']) for c in self.chunks]
            self.bm25 = BM25Okapi(tokenized)
    
    @staticmethod
    def _tokenize(text):
        return re.findall(r'\w+', text.lower())

    def retrieve(self, query:str, k:int=3, alpha:float=0.5, max_distance:float = 0.7):
        """Hybrid retrieval using Dense + bm25 and then rank using RRF fusion"""
        if not self.chunks:
            return []

        # Dense
        dense = self.collection.query(query_texts=[query], n_results=min(20, len(self.chunks)))
        dense_filtered = [
            (name, dist) for name, dist in zip(
                [m['name'] for m in dense['metadatas'][0]],
                dense['distances'][0]
            ) if dist < max_distance
        ]
        dense_names = [name for name, dist in dense_filtered]

        # bm25
        bm25_scores = self.bm25.get_scores(self._tokenize(query))
        bm25_ranked = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)
        bm25_names = [self.chunks[i]['name'] for i in bm25_ranked[:20]]

        # RRF Fusion
        def rrf_score(ranked_list, item):
            if item not in ranked_list:
                return 0
            return 1 / (60 + ranked_list.index(item) + 1)
        
        all_names = set(dense_names) | set(bm25_names)
        scored = [
            (name, alpha * rrf_score(dense_names, name) + (1-alpha) * rrf_score(bm25_names, name))
            for name in all_names
        ]
        scored.sort(key=lambda x:x[1], reverse=True)

        # Return actual chunks
        top_names = [name for name, _ in scored[:k]]
        name_to_chunk = {c['name']: c for c in self.chunks}
        return [name_to_chunk[n] for n in top_names if n in name_to_chunk]



