# =================== AIPass ====================
# Name: embed_subprocess.py
# Description: Embedding Subprocess Handler
# Version: 2.1.0
# Created: 2026-03-12
# Modified: 2026-11-21
# =============================================

"""Embedding Subprocess Handler: JSON {"texts": [...]} on stdin, JSON embeddings on stdout (fastembed, no torch)."""

import sys
import json


def _reason(exc: Exception) -> str:
    """The refusal text; fastembed's offline miss gets what is missing and how to get it."""
    text = str(exc)
    if not text.startswith("Could not load model"):
        return text
    from fastembed.common.utils import define_cache_dir

    return (
        f"{text} The model is not in fastembed's cache at {define_cache_dir()} and could not be fetched: "
        "it has to be downloaded once with network access. Run any 'drone @memory search \"<words>\"' "
        "while online and fastembed downloads it (Hugging Face qdrant/all-MiniLM-L6-v2-onnx, or its "
        "storage.googleapis.com mirror) into that directory; FASTEMBED_CACHE_PATH sets where that cache lives."
    )


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
        print(json.dumps({"success": False, "error": _reason(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
