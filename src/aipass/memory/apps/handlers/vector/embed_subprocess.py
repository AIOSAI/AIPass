# =================== AIPass ====================
# Name: embed_subprocess.py
# Description: Embedding Subprocess Handler
# Version: 2.1.0
# Created: 2026-03-12
# Modified: 2026-10-17
# =============================================

"""
Embedding Subprocess Handler

JSON {"texts": [...]} on stdin, JSON embeddings on stdout (fastembed, no torch).
"""

import sys
import json


def main():
    """Process embedding request from stdin JSON."""
    try:
        input_data = json.load(sys.stdin)
        texts = input_data.get("texts", [])

        if not texts:
            print(json.dumps({"success": True, "embeddings": [], "count": 0, "dimension": 384}))
            return

        from fastembed import TextEmbedding

        model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")

        # batch_size=1: pad 128 / truncate 256 makes mixed-length batches ragged ("inhomogeneous shape").
        ordered = [vector.tolist() for vector in model.embed(list(texts), batch_size=1)]

        print(json.dumps({"success": True, "embeddings": ordered, "count": len(ordered), "dimension": 384}))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
