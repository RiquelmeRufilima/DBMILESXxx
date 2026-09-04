from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import UserPreference, UserProfile, WebUser


def _ensure_default_row(db: Session, model, user_id: int) -> bool:
    """Cria um registro padrão somente se ele realmente não existir.

    Não usa apenas user.profile/user.preference porque essas relações podem estar
    carregadas como None em uma instância antiga do usuário, mesmo quando outra
    requisição já criou o registro no PostgreSQL.

    O SAVEPOINT também protege contra duas Functions da Vercel tentando criar o
    mesmo padrão ao mesmo tempo.
    """
    if db.get(model, user_id) is not None:
        return False

    try:
        with db.begin_nested():
            # Reconsulta dentro do SAVEPOINT para reduzir a janela de corrida.
            if db.get(model, user_id) is None:
                db.add(model(user_id=user_id))
                db.flush()
                return True
    except IntegrityError:
        # Outra requisição pode ter criado a mesma linha entre a consulta e o
        # INSERT. O conflito fica restrito ao SAVEPOINT e não derruba a sessão.
        return False

    return False


def ensure_user_defaults(db: Session, user: WebUser) -> None:
    """Garante perfil e preferências do usuário de forma idempotente.

    Pode ser chamada várias vezes, inclusive por Functions concorrentes, sem
    tentar inserir novamente a mesma PK em web_user_profiles ou
    web_user_preferences.
    """
    user_id = int(user.id)

    created_profile = _ensure_default_row(db, UserProfile, user_id)
    created_preference = _ensure_default_row(db, UserPreference, user_id)

    if created_profile or created_preference:
        db.commit()

    # Se as relações já tinham sido carregadas como None, força uma nova leitura
    # na próxima vez que forem acessadas.
    try:
        db.expire(user, ["profile", "preference"])
    except Exception:
        # Não transforma uma simples atualização de cache em erro da requisição.
        pass
