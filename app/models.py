from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship as orm_relationship

from .database import Base


class WebCompany(Base):
    __tablename__ = "web_companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    cnpj: Mapped[str | None] = mapped_column(String(30), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(180), nullable=True)
    logo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    users: Mapped[list["WebUser"]] = orm_relationship(back_populates="company")


class WebUser(Base):
    __tablename__ = "web_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(180), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contact_id: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(30), default="membro", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    legacy_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    company: Mapped[WebCompany | None] = orm_relationship(back_populates="users")
    quotes: Mapped[list["WebQuote"]] = orm_relationship(back_populates="user")
    profile: Mapped["UserProfile | None"] = orm_relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    preference: Mapped["UserPreference | None"] = orm_relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    notifications: Mapped[list["Notification"]] = orm_relationship(back_populates="user", cascade="all, delete-orphan")


# Um mesmo endereço não pode virar duas contas por diferenças de caixa/espaços.
# Bancos existentes recebem este índice pelo script de migração auditável.
Index("ux_web_users_email_normalized", func.lower(func.trim(WebUser.email)), unique=True)


class UserProfile(Base):
    __tablename__ = "web_user_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), primary_key=True)
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    avatar_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user: Mapped[WebUser] = orm_relationship(back_populates="profile")


class UserPreference(Base):
    __tablename__ = "web_user_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), primary_key=True)
    theme_mode: Mapped[str] = mapped_column(String(20), default="dark", nullable=False)
    theme_preset: Mapped[str] = mapped_column(String(30), default="ocean", nullable=False)
    accent_color: Mapped[str] = mapped_column(String(20), default="#26c5e6", nullable=False)
    background_style: Mapped[str] = mapped_column(String(30), default="gradient", nullable=False)
    compact_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    in_app_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    settings_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user: Mapped[WebUser] = orm_relationship(back_populates="preference")


class Airline(Base):
    __tablename__ = "web_airlines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id"), nullable=True, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("web_users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    logo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    color: Mapped[str] = mapped_column(String(20), default="#24b7d3", nullable=False)
    engine_type: Mapped[str] = mapped_column(String(30), default="formula", nullable=False)
    legacy_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    market_scope: Mapped[str] = mapped_column(String(20), default="both", nullable=False)
    partner_airlines_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    calculation_types: Mapped[list["CalculationType"]] = orm_relationship(
        back_populates="airline", cascade="all, delete-orphan", order_by="CalculationType.id"
    )


class CalculationType(Base):
    __tablename__ = "web_calculation_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    airline_id: Mapped[int] = mapped_column(ForeignKey("web_airlines.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    formula: Mapped[str] = mapped_column(Text, default="(milhas * milheiro) + taxa", nullable=False)
    apply_mode: Mapped[str] = mapped_column(String(30), default="total", nullable=False)
    legacy_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    airline: Mapped[Airline] = orm_relationship(back_populates="calculation_types")
    fields: Mapped[list["CalculationField"]] = orm_relationship(
        back_populates="calculation_type", cascade="all, delete-orphan", order_by="CalculationField.order_index"
    )


class CalculationField(Base):
    __tablename__ = "web_calculation_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    calculation_type_id: Mapped[int] = mapped_column(ForeignKey("web_calculation_types.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(180), nullable=False)
    field_type: Mapped[str] = mapped_column(String(30), default="number", nullable=False)
    default_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    step: Mapped[float | None] = mapped_column(Float, nullable=True)
    help_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    calculation_type: Mapped[CalculationType] = orm_relationship(back_populates="fields")


class WebQuote(Base):
    __tablename__ = "web_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    legacy_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id"), nullable=True, index=True)
    airline_id: Mapped[int | None] = mapped_column(ForeignKey("web_airlines.id"), nullable=True)
    calculation_type_id: Mapped[int | None] = mapped_column(ForeignKey("web_calculation_types.id"), nullable=True)
    quote_name: Mapped[str] = mapped_column(String(180), default="Nova cotação", nullable=False)
    origin: Mapped[str | None] = mapped_column(String(80), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(80), nullable=True)
    passengers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    babies: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bags: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="BRL", nullable=False)
    input_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    breakdown_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user: Mapped[WebUser] = orm_relationship(back_populates="quotes")
    airline: Mapped[Airline | None] = orm_relationship()
    calculation_type: Mapped[CalculationType | None] = orm_relationship()
    trip: Mapped["QuoteTripDetail | None"] = orm_relationship(back_populates="quote", cascade="all, delete-orphan", uselist=False)
    commercial: Mapped["QuoteCommercial | None"] = orm_relationship(back_populates="quote", cascade="all, delete-orphan", uselist=False)
    pdf_settings: Mapped["QuotePdfSetting | None"] = orm_relationship(back_populates="quote", cascade="all, delete-orphan", uselist=False)


class QuoteTripDetail(Base):
    __tablename__ = "web_quote_trip_details"

    quote_id: Mapped[int] = mapped_column(ForeignKey("web_quotes.id", ondelete="CASCADE"), primary_key=True)
    travel_type: Mapped[str] = mapped_column(String(30), default="round_trip", nullable=False)
    departure_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    return_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    segments_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    client_email: Mapped[str | None] = mapped_column(String(180), nullable=True)
    client_phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_person_id: Mapped[int | None] = mapped_column(ForeignKey("web_persons.id"), nullable=True)

    quote: Mapped[WebQuote] = orm_relationship(back_populates="trip")


class QuoteCommercial(Base):
    __tablename__ = "web_quote_commercial"

    quote_id: Mapped[int] = mapped_column(ForeignKey("web_quotes.id", ondelete="CASCADE"), primary_key=True)
    sale_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_basis: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    sent_to_client_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    card_difference_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    card_installment_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    card_total_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    card_interest_mode: Mapped[str] = mapped_column(String(20), default="cash", nullable=False)
    card_installments: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    quote: Mapped[WebQuote] = orm_relationship(back_populates="commercial")


class QuotePdfSetting(Base):
    __tablename__ = "web_quote_pdf_settings"

    quote_id: Mapped[int] = mapped_column(ForeignKey("web_quotes.id", ondelete="CASCADE"), primary_key=True)
    show_company_logo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    show_system_brand: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    custom_title: Mapped[str | None] = mapped_column(String(220), nullable=True)
    custom_client_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    custom_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    quote: Mapped[WebQuote] = orm_relationship(back_populates="pdf_settings")


class ChatMessage(Base):
    __tablename__ = "web_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("web_companies.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id"), index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attachment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attachment_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user: Mapped[WebUser] = orm_relationship()




class UserChatContact(Base):
    __tablename__ = "web_user_chat_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), index=True)
    contact_user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    owner: Mapped[WebUser] = orm_relationship(foreign_keys=[owner_user_id])
    contact: Mapped[WebUser] = orm_relationship(foreign_keys=[contact_user_id])


class PrivateChatMessage(Base):
    __tablename__ = "web_private_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id", ondelete="SET NULL"), nullable=True, index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    sender: Mapped[WebUser] = orm_relationship(foreign_keys=[sender_id])
    recipient: Mapped[WebUser] = orm_relationship(foreign_keys=[recipient_id])


class Notification(Base):
    __tablename__ = "web_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), default="info", nullable=False)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    user: Mapped[WebUser] = orm_relationship(back_populates="notifications")


class PushSubscription(Base):
    """Um navegador/dispositivo autorizado por usuário (Web Push)."""
    __tablename__ = "web_push_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class CheckinReminder(Base):
    """Idempotência do aviso, inclusive quando o cron repete execução."""
    __tablename__ = "web_checkin_reminders"
    __table_args__ = (UniqueConstraint("user_id", "flight_key", name="uq_checkin_user_flight"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), index=True)
    flight_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PublicQuoteLink(Base):
    __tablename__ = "web_public_quote_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id"), nullable=True, index=True)
    token: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(180), default="Solicite sua cotação", nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    max_uses: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    total_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    owner: Mapped[WebUser] = orm_relationship()
    requests: Mapped[list["QuoteRequest"]] = orm_relationship(back_populates="public_link", cascade="all, delete-orphan")


class QuoteRequest(Base):
    __tablename__ = "web_quote_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("web_public_quote_links.id", ondelete="CASCADE"), index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id"), nullable=True, index=True)
    client_name: Mapped[str] = mapped_column(String(180), nullable=False)
    phone: Mapped[str] = mapped_column(String(60), nullable=False)
    email: Mapped[str | None] = mapped_column(String(180), nullable=True)
    travel_type: Mapped[str] = mapped_column(String(30), default="round_trip", nullable=False)
    origin: Mapped[str] = mapped_column(String(80), nullable=False)
    destination: Mapped[str] = mapped_column(String(80), nullable=False)
    departure_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    return_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    adults: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    children: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    babies: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bags: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    segments_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="recebida", nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    public_link: Mapped[PublicQuoteLink] = orm_relationship(back_populates="requests")


# ============================================================
# V5.5 - COTAÇÃO PRINCIPAL + OPÇÕES POR COMPANHIA
# ============================================================
class QuoteGroup(Base):
    __tablename__ = "web_quote_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id"), nullable=True, index=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("web_users.id"), nullable=True, index=True)
    quote_name: Mapped[str] = mapped_column(String(180), default="Nova cotação", nullable=False)
    origin: Mapped[str | None] = mapped_column(String(80), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(80), nullable=True)
    passengers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    babies: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bags: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_request_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="aberta", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user: Mapped[WebUser] = orm_relationship(foreign_keys=[user_id])
    assigned_user: Mapped[WebUser | None] = orm_relationship(foreign_keys=[assigned_user_id])
    trip: Mapped["QuoteGroupTripDetail | None"] = orm_relationship(back_populates="group", cascade="all, delete-orphan", uselist=False)
    option_links: Mapped[list["QuoteOptionIndex"]] = orm_relationship(back_populates="group", cascade="all, delete-orphan", order_by="QuoteOptionIndex.position")


class QuoteGroupTripDetail(Base):
    __tablename__ = "web_quote_group_trip_details"

    group_id: Mapped[int] = mapped_column(ForeignKey("web_quote_groups.id", ondelete="CASCADE"), primary_key=True)
    travel_type: Mapped[str] = mapped_column(String(30), default="round_trip", nullable=False)
    departure_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    return_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    segments_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    client_email: Mapped[str | None] = mapped_column(String(180), nullable=True)
    client_phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_person_id: Mapped[int | None] = mapped_column(ForeignKey("web_persons.id"), nullable=True)
    variants_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    flexibility_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    group: Mapped[QuoteGroup] = orm_relationship(back_populates="trip")


class QuoteOptionIndex(Base):
    __tablename__ = "web_quote_option_index"

    quote_id: Mapped[int] = mapped_column(ForeignKey("web_quotes.id", ondelete="CASCADE"), primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("web_quote_groups.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    group: Mapped[QuoteGroup] = orm_relationship(back_populates="option_links")
    quote: Mapped[WebQuote] = orm_relationship()



class AcceptedQuote(Base):
    __tablename__ = "web_accepted_quotes"

    group_id: Mapped[int] = mapped_column(ForeignKey("web_quote_groups.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id"), nullable=True, index=True)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("web_quotes.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="aceita", nullable=False)
    channel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    locator: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sale_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    payment_status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    invoice_status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    selected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)

    group: Mapped[QuoteGroup] = orm_relationship()
    user: Mapped[WebUser] = orm_relationship()
    quote: Mapped[WebQuote | None] = orm_relationship()


class FlightRegistry(Base):
    __tablename__ = "web_flight_registry"

    group_id: Mapped[int] = mapped_column(ForeignKey("web_quote_groups.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id"), nullable=True, index=True)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("web_quotes.id"), nullable=True, index=True)
    notification_mode: Mapped[str | None] = mapped_column(String(60), nullable=True)
    locator: Mapped[str | None] = mapped_column(String(80), nullable=True)
    flight_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    airline_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    departure_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    arrival_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    checkin_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extra_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    selected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)

    group: Mapped[QuoteGroup] = orm_relationship()
    user: Mapped[WebUser] = orm_relationship()
    quote: Mapped[WebQuote | None] = orm_relationship()


class QuoteActivity(Base):
    __tablename__ = "web_quote_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id"), nullable=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("web_quote_groups.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id"), index=True)
    event: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    actor: Mapped[WebUser] = orm_relationship(foreign_keys=[actor_user_id])
    group: Mapped[QuoteGroup] = orm_relationship()


class QuoteBoardStatus(Base):
    __tablename__ = "web_quote_board_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("web_users.id"), nullable=True, index=True)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(180), nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="#8d8d8d", nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AuthEmailCode(Base):
    __tablename__ = "web_auth_email_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class CompanyTask(Base):
    __tablename__ = "web_company_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id"), nullable=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id"), index=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("web_users.id"), nullable=True, index=True)
    quote_group_id: Mapped[int | None] = mapped_column(ForeignKey("web_quote_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pendente", nullable=False, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    photo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    created_by: Mapped[WebUser] = orm_relationship(foreign_keys=[created_by_user_id])
    assigned_user: Mapped[WebUser | None] = orm_relationship(foreign_keys=[assigned_user_id])
    quote_group: Mapped[QuoteGroup | None] = orm_relationship(foreign_keys=[quote_group_id])


# ============================================================
# V5.6 - CADASTRO DE PESSOAS (CLIENTES/PASSAGEIROS)
# ============================================================

class Person(Base):
    """Cadastro de pessoas (clientes, passageiros, fornecedores, representantes)"""
    __tablename__ = "web_persons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("web_users.id"), nullable=True, index=True)
    
    # Dados principais (obrigatórios)
    name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    cpf_cnpj: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True, index=True)
    birth_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    
    # Tipo de pessoa
    person_type: Mapped[str] = mapped_column(String(30), default="passageiro", nullable=False)
    
    # Contato
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(180), nullable=True)
    website: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pix_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    accepts_communication: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Documentos
    rg: Mapped[str | None] = mapped_column(String(30), nullable=True)
    foreign_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    passport: Mapped[str | None] = mapped_column(String(30), nullable=True)
    passport_issue_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    passport_expiry_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    passport_nationality: Mapped[str | None] = mapped_column(String(60), nullable=True)
    visa: Mapped[str | None] = mapped_column(String(30), nullable=True)
    visa_expiry_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    issuing_agency: Mapped[str | None] = mapped_column(String(60), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(60), nullable=True)
    marital_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    
    # Informações adicionais
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    profession: Mapped[str | None] = mapped_column(String(100), nullable=True)
    income: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sales_channel: Mapped[str | None] = mapped_column(String(60), nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(180), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    
    # Endereço
    country: Mapped[str | None] = mapped_column(String(60), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    state: Mapped[str | None] = mapped_column(String(60), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    neighborhood: Mapped[str | None] = mapped_column(String(80), nullable=True)
    street: Mapped[str | None] = mapped_column(String(200), nullable=True)
    number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    complement: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    # Observações
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Status
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    legacy_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relacionamentos
    company: Mapped[WebCompany | None] = orm_relationship()
    user: Mapped[WebUser | None] = orm_relationship()
    
    family_members: Mapped[list["PersonFamily"]] = orm_relationship(back_populates="person", foreign_keys="PersonFamily.person_id", cascade="all, delete-orphan")
    attachments: Mapped[list["PersonAttachment"]] = orm_relationship(back_populates="person", cascade="all, delete-orphan")


class PersonFamily(Base):
    """Membros da família de uma pessoa"""
    __tablename__ = "web_person_family"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("web_persons.id", ondelete="CASCADE"), index=True)
    relative_id: Mapped[int] = mapped_column(ForeignKey("web_persons.id"), index=True)
    relationship: Mapped[str] = mapped_column(String(30), nullable=False)
    
    person: Mapped["Person"] = orm_relationship(back_populates="family_members", foreign_keys=[person_id])
    relative: Mapped["Person"] = orm_relationship(foreign_keys=[relative_id])


class PersonAttachment(Base):
    """Anexos de uma pessoa"""
    __tablename__ = "web_person_attachments"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("web_persons.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    person: Mapped["Person"] = orm_relationship(back_populates="attachments")

# ---------------------------------------------------------------------------
# Segurança: limite de tentativas e bloqueio feito pelo administrador.
# Tabelas criadas sob demanda (services/protection.py) para funcionar no
# Vercel/Neon sem migração no cold start.
# ---------------------------------------------------------------------------
class AuthAttempt(Base):
    """Registro de tentativas (login, códigos, convites) para limitar abusos."""
    __tablename__ = "web_auth_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class UserAccessBlock(Base):
    """Usuário bloqueado pelo administrador (diferente de e-mail não confirmado)."""
    __tablename__ = "web_user_access_blocks"

    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), primary_key=True)
    blocked_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Etiquetas do histórico
# ---------------------------------------------------------------------------
class QuoteTag(Base):
    """Etiqueta da empresa (ou do usuário, quando ele não tem empresa)."""
    __tablename__ = "web_quote_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("web_users.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    color: Mapped[str] = mapped_column(String(9), default="#26c5e6", nullable=False)
    # Tipo: "cotacao", "voo" ou "pessoa" (onde a etiqueta pode ser usada)
    kind: Mapped[str] = mapped_column(String(20), default="cotacao", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class QuoteTagLink(Base):
    """Liga uma etiqueta a um item do histórico.

    target_kind: "group" (cotação principal), "quote" (cotação antiga/avulsa),
    "flight" (trecho de voo: group_id * 1000 + índice do trecho) ou "person".
    """
    __tablename__ = "web_quote_tag_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("web_quote_tags.id", ondelete="CASCADE"), nullable=False, index=True)
    target_kind: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Reservas aéreas importadas pelo localizador (base para Amadeus/conectores)
# ---------------------------------------------------------------------------
class AirlineReservation(Base):
    """Reserva informada pelo localizador (como em MilhasPix/Iddas).

    Fica salva mesmo sem conector ativo (status "pendente"); quando um conector
    de busca estiver configurado, os voos e passageiros são preenchidos.
    """
    __tablename__ = "web_airline_reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("web_companies.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("web_users.id", ondelete="SET NULL"), nullable=True, index=True)
    airline_slug: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    airline_name: Mapped[str] = mapped_column(String(120), nullable=False)
    locator: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    purchase_number: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    origin: Mapped[str | None] = mapped_column(String(3), nullable=True)
    notify_changes: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # pendente | sincronizada | nao_encontrada | erro
    status: Mapped[str] = mapped_column(String(20), default="pendente", nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    booking_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    passengers_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    flights_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    total_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user: Mapped[WebUser | None] = orm_relationship()


class ChatAttachment(Base):
    """Anexo de mensagem do chat (privado ou equipe). Tabela criada sob demanda.

    kind: "private" (PrivateChatMessage) ou "group" (ChatMessage).
    storage_json guarda onde o arquivo está (Vercel Blob ou disco local);
    o arquivo só é entregue pela rota autenticada /company/chat/arquivos/{id}.
    """
    __tablename__ = "web_chat_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    company_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    uploader_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    recipient_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(120), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    storage_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ChatMessageFlag(Base):
    """Marcações das mensagens do chat: fixar, favoritar e denunciar.

    kind: "group" (ChatMessage) ou "private" (PrivateChatMessage).
    flag: "pin" (visível para todos da conversa), "fav" (só para quem marcou)
    ou "report" (registro de denúncia). Tabela criada sob demanda.
    """
    __tablename__ = "web_chat_message_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    flag: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    company_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


# Índices compostos das consultas incrementais mais frequentes.
Index("ix_chat_company_recent", ChatMessage.company_id, ChatMessage.id)
Index("ix_pv_sender_recipient_recent", PrivateChatMessage.sender_id, PrivateChatMessage.recipient_id, PrivateChatMessage.id)
Index("ix_pv_recipient_sender_recent", PrivateChatMessage.recipient_id, PrivateChatMessage.sender_id, PrivateChatMessage.id)
Index("ix_pv_unread_recipient", PrivateChatMessage.recipient_id, PrivateChatMessage.is_read)
Index("ix_person_company_progress", Person.company_id, Person.is_complete, Person.created_at, Person.id)
Index("ix_person_user_progress", Person.user_id, Person.is_complete, Person.created_at, Person.id)
