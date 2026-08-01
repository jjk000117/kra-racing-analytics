from __future__ import annotations

import json

from kra_analytics.profiling import build_raw_profile

if __name__ == "__main__":
    print(json.dumps(build_raw_profile(), ensure_ascii=True, indent=2))
