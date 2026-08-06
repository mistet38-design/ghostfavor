import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class NiveauFiabilite(str, enum.Enum):
    bronze = "bronze"
    argent = "argent"
    or_ = "or"
    platine = "platine"


class TypeAnnonce(str, enum.Enum):
    offre = "offre"
    demande = "demande"


class StatutAnnonce(str, enum.Enum):
    ouverte = "ouverte"
    matchee = "matchee"
    annulee = "annulee"
    expiree = "expiree"


class StatutEchange(str, enum.Enum):
    en_attente = "en_attente"
    accepte = "accepte"
    en_cours = "en_cours"
    preuve_soumise = "preuve_soumise"
    valide = "valide"
    litige = "litige"
    annule = "annule"


class TypeTransaction(str, enum.Enum):
    depot = "depot"
    retrait = "retrait"
    escrow_hold = "escrow_hold"
    escrow_release = "escrow_release"
    commission = "commission"


class StatutSignalement(str, enum.Enum):
    ouvert = "ouvert"
    en_revue = "en_revue"
    resolu = "resolu"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telephone: Mapped[str] = mapped_column(String(20), nullable=True)
    prenom: Mapped[str] = mapped_column(String(100))
    ville: Mapped[str] = mapped_column(String(100), nullable=True)
    latitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[float] = mapped_column(Numeric(9, 6), nullable=True)

    score: Mapped[int] = mapped_column(Integer, default=50)
    niveau: Mapped[NiveauFiabilite] = mapped_column(
        Enum(NiveauFiabilite), default=NiveauFiabilite.bronze
    )
    solde_stars: Mapped[int] = mapped_column(Integer, default=0)

    regles_acceptees: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_complet: Mapped[bool] = mapped_column(Boolean, default=False)
    banni: Mapped[bool] = mapped_column(Boolean, default=False)
    langue: Mapped[str] = mapped_column(String(5), default="fr")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Annonce(Base):
    __tablename__ = "annonces"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[TypeAnnonce] = mapped_column(Enum(TypeAnnonce), index=True)
    categorie: Mapped[str] = mapped_column(String(50), index=True)  # clé dans config.CATEGORIES
    description: Mapped[str] = mapped_column(String(280))

    ville: Mapped[str] = mapped_column(String(100), index=True)
    rayon_km: Mapped[int] = mapped_column(Integer, default=5)

    creneau_debut: Mapped[datetime] = mapped_column(DateTime)
    creneau_fin: Mapped[datetime] = mapped_column(DateTime, index=True)

    depot_stars: Mapped[int] = mapped_column(Integer)
    statut: Mapped[StatutAnnonce] = mapped_column(
        Enum(StatutAnnonce), default=StatutAnnonce.ouverte, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship()


class Echange(Base):
    __tablename__ = "echanges"

    id: Mapped[int] = mapped_column(primary_key=True)
    annonce_offre_id: Mapped[int] = mapped_column(ForeignKey("annonces.id"))
    annonce_demande_id: Mapped[int] = mapped_column(ForeignKey("annonces.id"))

    partie_a_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    partie_b_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    statut: Mapped[StatutEchange] = mapped_column(
        Enum(StatutEchange), default=StatutEchange.en_attente, index=True
    )
    montant_escrow: Mapped[int] = mapped_column(Integer)

    preuve_file_id: Mapped[str] = mapped_column(String(255), nullable=True)
    preuve_type: Mapped[str] = mapped_column(String(20), nullable=True)  # photo | vocal

    confirmation_a: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmation_b: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    accepte_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    valide_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    type: Mapped[TypeTransaction] = mapped_column(Enum(TypeTransaction))
    montant: Mapped[int] = mapped_column(Integer)
    echange_id: Mapped[int] = mapped_column(ForeignKey("echanges.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ScoreLog(Base):
    __tablename__ = "score_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    delta: Mapped[int] = mapped_column(Integer)
    raison: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Signalement(Base):
    __tablename__ = "signalements"

    id: Mapped[int] = mapped_column(primary_key=True)
    echange_id: Mapped[int] = mapped_column(ForeignKey("echanges.id"))
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    raison: Mapped[str] = mapped_column(Text)
    statut: Mapped[StatutSignalement] = mapped_column(
        Enum(StatutSignalement), default=StatutSignalement.ouvert
    )
    notes_admin: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
