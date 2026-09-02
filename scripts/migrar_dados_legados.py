from __future__ import annotations

import argparse
from pathlib import Path

from app.database import Base, SessionLocal, engine
from app.services.legacy_migration import migrate_legacy_data
from app.services.seed import seed_builtin_airlines


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra o banco antigo do DBMILESX para a estrutura Web V5.")
    parser.add_argument("--origem", type=Path, default=None, help="Caminho do sistema_aereo_secure.db antigo")
    parser.add_argument("--forcar", action="store_true", help="Tenta migrar mesmo se já existirem usuários")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_builtin_airlines(db)
        result = migrate_legacy_data(db, legacy_path=args.origem, force=args.forcar)
        print("\nMigração concluída:")
        for key, value in result.items():
            print(f"  {key}: {value}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
