"""Register definitions without generating market observations."""
import json
from sqlalchemy.orm import Session
from packages.domain.config import registry
from packages.domain.models import IndicatorDefinition
from packages.domain.store import engine


def sync_registry(session: Session):
    for item in registry(phase2=True).values():
        if session.get(IndicatorDefinition, item["id"]) is None:
            session.add(IndicatorDefinition(**{**item, "source_priority": json.dumps(item["source_priority"])}))
    session.commit()


if __name__ == "__main__":
    with Session(engine()) as session:
        sync_registry(session)
