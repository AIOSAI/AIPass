# =================== AIPass ====================
# Name: embed_subprocess.py
# Description: Embedding Subprocess Handler
# Version: 1.0.0
# Created: 2026-03-12
# Modified: 2026-03-12
# =============================================

"""
Embedding Subprocess Handler

Called via subprocess from rollover orchestrator to ensure sentence-transformers
and torch run in the memory-specific venv (AIPASS_MEMORY_PYTHON).

Input: JSON on stdin with texts to encode
Output: JSON on stdout with embeddings
"""

import sys
import json


def main():
    """Process embedding request from stdin JSON"""
    try:
        input_data = json.load(sys.stdin)
        texts = input_data.get("texts", [])

        if not texts:
            print(json.dumps({"success": True, "embeddings": [], "count": 0, "dimension": 384}))
            return

        # Import here — runs in memory venv where these are installed
        from sentence_transformers import SentenceTransformer
        import torch

        model = SentenceTransformer("all-MiniLM-L6-v2")

        use_gpu = torch.cuda.is_available()
        if use_gpu:
            model = model.to("cuda")
            batch_size = 64
        else:
            batch_size = 16

        # Pre-sort by length (reduces padding waste)
        sorted_pairs = sorted(enumerate(texts), key=lambda x: len(x[1]))
        sorted_indices, sorted_texts = zip(*sorted_pairs)

        # Encode
        embeddings = model.encode(
            list(sorted_texts),
            batch_size=batch_size,
            convert_to_tensor=False,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        # Restore original order
        ordered = [None] * len(texts)
        for orig_idx, sorted_idx in enumerate(sorted_indices):
            ordered[sorted_idx] = embeddings[orig_idx].tolist()

        if use_gpu:
            torch.cuda.empty_cache()

        print(json.dumps({"success": True, "embeddings": ordered, "count": len(ordered), "dimension": 384}))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
