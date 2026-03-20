"""
Lightweight OpenAI-compatible embedding API server for bge-large-en-v1.5.
Runs on port 8002, serves /v1/embeddings endpoint.
"""
import json
import torch
import numpy as np
from http.server import HTTPServer, BaseHTTPRequestHandler
from transformers import AutoTokenizer, AutoModel

MODEL_PATH = "/home/models/bge-large-en-v1.5"
PORT = 8002

print(f"Loading model from {MODEL_PATH}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
model = AutoModel.from_pretrained(MODEL_PATH)
model.eval()
if torch.cuda.is_available():
    model = model.cuda()
    print("Model loaded on GPU")
else:
    print("Model loaded on CPU")

def get_embeddings(texts):
    encoded = tokenizer(texts, padding=True, truncation=True, max_length=512, return_tensors="pt")
    if torch.cuda.is_available():
        encoded = {k: v.cuda() for k, v in encoded.items()}
    with torch.no_grad():
        output = model(**encoded)
    # Use CLS token embedding
    embeddings = output.last_hidden_state[:, 0, :].cpu().numpy()
    # Normalize
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / norms
    return embeddings.tolist()

class EmbeddingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/v1/embeddings":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            inp = body.get("input", [])
            if isinstance(inp, str):
                inp = [inp]
            embeddings = get_embeddings(inp)
            resp = {
                "object": "list",
                "data": [
                    {"object": "embedding", "index": i, "embedding": emb}
                    for i, emb in enumerate(embeddings)
                ],
                "model": body.get("model", "bge-large-en-v1.5"),
                "usage": {"prompt_tokens": 0, "total_tokens": 0}
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"[EmbeddingServer] {args[0]}")

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), EmbeddingHandler)
    print(f"Embedding server running on port {PORT}")
    server.serve_forever()
