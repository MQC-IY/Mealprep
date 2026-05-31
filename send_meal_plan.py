#!/usr/bin/env python3
"""Send the weekly meal prep plan via email using SMTP."""

from __future__ import annotations

import os
import re
import smtplib
import ssl
import sys
from html import escape
from email.message import EmailMessage
from pathlib import Path

from meal_plan_generator import (
    DEFAULT_VARIANT,
    PLAN_VARIANTS,
    generate_all_variants,
    generate_weekly_files,
    validate_variant,
)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key or key in os.environ:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ[key] = value


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Umgebungsvariable fehlt: {name}")
    return value


def parse_recipients(raw_value: str, env_name: str) -> list[str]:
    recipients = [address.strip() for address in raw_value.split(",") if address.strip()]
    if not recipients:
        raise RuntimeError(f"{env_name} enthält keine gültigen Empfänger.")
    return recipients


def resolve_variants() -> list[str]:
    raw_variants = os.getenv("MEALPLAN_VARIANTS")
    if not raw_variants:
        return [validate_variant(os.getenv("MEALPLAN_VARIANT", DEFAULT_VARIANT).strip())]

    variants: list[str] = []
    for raw_variant in raw_variants.split(","):
        variant = raw_variant.strip().lower()
        if not variant:
            continue
        if variant == "all":
            variants.extend(PLAN_VARIANTS)
            continue
        variants.append(validate_variant(variant))

    if not variants:
        raise RuntimeError("MEALPLAN_VARIANTS enthält keine gültige Variante.")

    return list(dict.fromkeys(variants))


def variant_env_name(base_name: str, variant: str) -> str:
    return f"{base_name}_{variant.upper()}"


def variant_env(base_name: str, variant: str, *, allow_global: bool = True) -> str | None:
    return os.getenv(variant_env_name(base_name, variant)) or (
        os.getenv(base_name) if allow_global else None
    )


def resolve_subject(variant: str, multiple_variants: bool) -> str:
    variant_subject = os.getenv(variant_env_name("MEALPLAN_SUBJECT", variant))
    if variant_subject:
        return variant_subject

    subject = os.getenv("MEALPLAN_SUBJECT", "Wochenplan Meal Prep")
    if not multiple_variants:
        return subject

    variant_label = PLAN_VARIANTS[variant]["label"]
    return f"{subject} ({variant_label})"


def load_plan(path: Path) -> str:
    if not path.exists():
        raise RuntimeError(f"Datei nicht gefunden: {path}")
    return path.read_text(encoding="utf-8")


def load_optional_html(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def inline_markdown(text: str) -> str:
    escaped = escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def markdown_to_html(title: str, markdown_text: str) -> str:
    parts = [
        "<!DOCTYPE html>",
        '<html lang="de">',
        "<head>",
        '<meta charset="UTF-8" />',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />',
        f"<title>{escape(title)}</title>",
        (
            "<style>"
            "body{font-family:Arial,Helvetica,sans-serif;color:#2f241c;max-width:900px;"
            "margin:0 auto;padding:32px 24px;background:#fffdf9;line-height:1.6;}"
            "h1,h2,h3{font-family:Georgia,'Times New Roman',serif;color:#5b4335;}"
            "h1{font-size:32px;margin-top:0;} h2{font-size:26px;margin-top:28px;}"
            "h3{font-size:21px;margin-top:22px;} ul,ol{padding-left:22px;}"
            "li{margin:6px 0;} p{margin:12px 0;} code{background:#f3eadf;padding:1px 4px;"
            "border-radius:4px;} hr{border:none;border-top:1px solid #e2d4c4;margin:28px 0;}"
            "</style>"
        ),
        "</head>",
        "<body>",
    ]

    list_mode: str | None = None
    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            if list_mode:
                parts.append(f"</{list_mode}>")
                list_mode = None
            continue

        if stripped == "---":
            if list_mode:
                parts.append(f"</{list_mode}>")
                list_mode = None
            parts.append("<hr />")
            continue

        heading_match = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if heading_match:
            if list_mode:
                parts.append(f"</{list_mode}>")
                list_mode = None
            level = len(heading_match.group(1))
            parts.append(f"<h{level}>{inline_markdown(heading_match.group(2))}</h{level}>")
            continue

        bullet_match = re.match(r"^-\s+(.*)$", stripped)
        if bullet_match:
            if list_mode != "ul":
                if list_mode:
                    parts.append(f"</{list_mode}>")
                parts.append("<ul>")
                list_mode = "ul"
            parts.append(f"<li>{inline_markdown(bullet_match.group(1))}</li>")
            continue

        numbered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered_match:
            if list_mode != "ol":
                if list_mode:
                    parts.append(f"</{list_mode}>")
                parts.append("<ol>")
                list_mode = "ol"
            parts.append(f"<li>{inline_markdown(numbered_match.group(1))}</li>")
            continue

        if list_mode:
            parts.append(f"</{list_mode}>")
            list_mode = None
        parts.append(f"<p>{inline_markdown(stripped)}</p>")

    if list_mode:
        parts.append(f"</{list_mode}>")
    parts.append("</body></html>")
    return "\n".join(parts)


def extract_section(markdown_text: str, heading: str) -> str:
    lines = markdown_text.splitlines()
    start = None
    target = f"## {heading}"

    for index, line in enumerate(lines):
        if line.strip() == target:
            start = index
            break

    if start is None:
        raise RuntimeError(f"Abschnitt nicht gefunden: {heading}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break

    return "\n".join(lines[start:end]).strip() + "\n"


def add_html_attachment(message: EmailMessage, filename: str, title: str, markdown_text: str) -> None:
    attachment_html = markdown_to_html(title, markdown_text)
    message.add_attachment(
        attachment_html.encode("utf-8"),
        maintype="text",
        subtype="html",
        filename=filename,
    )


def embed_local_images(message: EmailMessage, html_text: str, base_dir: Path) -> None:
    pattern = re.compile(r'src="([^"]+)"')
    html_part = html_text
    related_files: list[tuple[str, Path]] = []

    for index, match in enumerate(pattern.findall(html_text), start=1):
        image_path = (base_dir / match).resolve()
        if image_path.suffix.lower() == ".svg":
            png_candidate = image_path.with_suffix(".png")
            if png_candidate.exists():
                html_part = html_part.replace(f'src="{match}"', f'src="{png_candidate.relative_to(base_dir).as_posix()}"')
                image_path = png_candidate
                match = png_candidate.relative_to(base_dir).as_posix()
        if not image_path.exists() or not image_path.is_file():
            continue
        cid = f"mealprep-image-{index}"
        html_part = html_part.replace(f'src="{match}"', f'src="cid:{cid}"')
        related_files.append((cid, image_path))

    message.add_alternative(html_part, subtype="html")
    html_message = message.get_payload()[-1]

    for cid, image_path in related_files:
        subtype = "svg+xml" if image_path.suffix.lower() == ".svg" else "png"
        html_message.add_related(
            image_path.read_bytes(),
            maintype="image",
            subtype=subtype,
            cid=f"<{cid}>",
            filename=image_path.name,
        )


def build_message(
    plan_text: str,
    recipes_text: str,
    html_text: str | None,
    *,
    recipients: list[str],
    subject: str,
    variant: str,
) -> EmailMessage:
    sender = require_env("MEALPLAN_SMTP_USER")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    plain_text = (
        "Hallo,\n\n"
        "anbei kommt euer aktueller Meal-Prep-Wochenplan.\n\n"
        f"{plan_text}\n"
    )
    message.set_content(plain_text)
    if html_text:
        newsletter_dir = Path(
            os.getenv(
                "MEALPLAN_HTML_BASE_DIR",
                Path(__file__).resolve().parent.as_posix(),
            )
        )
        embed_local_images(message, html_text, newsletter_dir)

    shopping_list_text = extract_section(plan_text, "Einkaufsliste für Deutschland")
    attachment_suffix = "" if variant == DEFAULT_VARIANT else f"_{variant}"
    add_html_attachment(
        message,
        f"einkaufsliste{attachment_suffix}.html",
        "Einkaufsliste für Deutschland",
        shopping_list_text,
    )
    add_html_attachment(
        message,
        f"rezepte{attachment_suffix}.html",
        "Rezepte zum Meal-Prep-Wochenplan",
        recipes_text,
    )
    return message


def send_email(message: EmailMessage) -> None:
    host = require_env("MEALPLAN_SMTP_HOST")
    port = int(os.getenv("MEALPLAN_SMTP_PORT", "465"))
    user = require_env("MEALPLAN_SMTP_USER")
    password = require_env("MEALPLAN_SMTP_PASSWORD")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context) as server:
        server.login(user, password)
        server.send_message(message)


def main() -> int:
    load_dotenv(Path(__file__).with_name(".env"))

    try:
        variants = resolve_variants()
        multiple_variants = len(variants) > 1
        sent_variants: list[str] = []
        generated_variants = generate_all_variants() if multiple_variants else None

        for variant in variants:
            generated_paths = (
                generated_variants[variant] if generated_variants else generate_weekly_files(variant=variant)
            )
            allow_global_files = not multiple_variants

            plan_path = Path(
                variant_env("MEALPLAN_FILE", variant, allow_global=allow_global_files)
                or generated_paths["plan"].as_posix()
            )
            newsletter_path = Path(
                variant_env("MEALPLAN_HTML_FILE", variant, allow_global=allow_global_files)
                or generated_paths["newsletter"].as_posix()
            )
            recipes_path = Path(
                variant_env("MEALPLAN_RECIPES_FILE", variant, allow_global=allow_global_files)
                or generated_paths["recipes"].as_posix()
            )

            recipients_env_name = variant_env_name("MEALPLAN_TO", variant)
            recipients_raw = os.getenv(recipients_env_name) or require_env("MEALPLAN_TO")
            recipients = parse_recipients(recipients_raw, recipients_env_name)

            plan_text = load_plan(plan_path)
            recipes_text = load_plan(recipes_path)
            html_text = load_optional_html(newsletter_path)
            message = build_message(
                plan_text,
                recipes_text,
                html_text,
                recipients=recipients,
                subject=resolve_subject(variant, multiple_variants),
                variant=variant,
            )
            send_email(message)
            sent_variants.append(variant)
    except Exception as exc:  # pragma: no cover - simple CLI error path
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    print(f"Meal-Prep-Plan wurde per E-Mail versendet: {', '.join(sent_variants)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
