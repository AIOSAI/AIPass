# =================== AIPass ====================
# Name: embed_subprocess.py
# Description: Embedding Subprocess Handler
# Version: 2.1.0
# Created: 2026-03-12
# Modified: 2026-10-03
# =============================================

"""
Embedding Subprocess Handler

Called via subprocess from rollover orchestrator to generate embeddings
using fastembed (ONNX runtime, no torch dependency).

Input: JSON on stdin with texts to encode
Output: JSON on stdout with embeddings
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

        # One text per batch. The model's tokenizer pads to a fixed 128 tokens but
        # truncates at 256, so a batch holding a text over 128 tokens beside a
        # shorter one gives numpy rows of different lengths and the whole batch
        # fails ("inhomogeneous shape"). ai_mail's sent folder met it on every purge
        # from 2026-09-28 (trigger digest 15638146; leg 9 of DPLAN-0354). 229 mails
        # embed in about 19 s this way.
        ordered = [vector.tolist() for vector in model.embed(list(texts), batch_size=1)]

        print(json.dumps({"success": True, "embeddings": ordered, "count": len(ordered), "dimension": 384}))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
