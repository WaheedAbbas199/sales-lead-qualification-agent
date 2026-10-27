"""Load SYNTHETIC demo leads (fictional businesses). Usage: python -m scripts.seed_demo"""

import json
from pathlib import Path

from app.core.config import get_settings
from app.db.session import make_engine, make_session_factory
from app.schemas.lead import LeadCreate
from app.services import icp_service, lead_service

DATA = Path(__file__).resolve().parent.parent / "data" / "sample_leads.json"


def main() -> None:
    factory = make_session_factory(make_engine(get_settings()))
    with factory() as s:
        icp_service.ensure_default(s)
        created = skipped = 0
        for row in json.loads(DATA.read_text()):
            try:
                lead_service.create_lead(s, LeadCreate(**row), actor_id=None, source_kind="seed")
                created += 1
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                print("skip:", row.get("email"), getattr(exc, "message", exc))
        print(f"Seeded {created} synthetic leads ({skipped} skipped). All businesses are fictional.")


if __name__ == "__main__":
    main()
