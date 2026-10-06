# modules/accounting.py
import os, csv, time, threading
from datetime import datetime
from typing import Optional

class NoOpAccountant:
    """Plug this in to disable accounting with zero overhead."""
    def log(self, **kwargs):  # signature compatible
        pass
    def close(self):  # for symmetry
        pass

class Accountant:
    """
    Thread-safe, append-only CSV logger for per-image API usage.
    Safe to use with ThreadPoolExecutor.
    """
    def __init__(
        self,
        csv_path: str = "results/usage_log.csv",
        model_name: str = "gemini-2.5-flash",
        price_per_1k_input: float = 0.0,
        price_per_1k_output: float = 0.0,
    ):
        # You can set prices via env or config if you like:
        # price_per_1k_input = float(os.getenv("PRICE_1K_IN", price_per_1k_input))
        # price_per_1k_output = float(os.getenv("PRICE_1K_OUT", price_per_1k_output))
        self.csv_path = csv_path
        self.model_name = model_name
        self.price_in = price_per_1k_input
        self.price_out = price_per_1k_output
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        self._ensure_header()

    def _ensure_header(self):
        if not os.path.exists(self.csv_path) or os.path.getsize(self.csv_path) == 0:
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([
                    "timestamp","image_file","model",
                    "input_tokens","output_tokens","total_tokens",
                    "processing_seconds",
                    "cost_input_usd","cost_output_usd","cost_total_usd",
                    "api_key_tail"
                ])

    def log(
        self,
        image_file: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        processing_seconds: float,
        api_key_used: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        model = model_name or self.model_name
        cost_in = (input_tokens / 1000.0) * self.price_in
        cost_out = (output_tokens / 1000.0) * self.price_out
        cost_total = cost_in + cost_out
        key_tail = (api_key_used[-6:] if api_key_used else "")

        row = [
            datetime.utcnow().isoformat(),
            image_file,
            model,
            input_tokens, output_tokens, total_tokens,
            round(processing_seconds, 4),
            round(cost_in, 6), round(cost_out, 6), round(cost_total, 6),
            key_tail
        ]
        with self._lock:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)

    def close(self):
        pass  # nothing to close; kept for future extensibility
