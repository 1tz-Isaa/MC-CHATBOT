from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "catalog.db"
SEED_PATH = DATA_DIR / "catalog_seed.json"
RAW_SUBMISSIONS_PATH = DATA_DIR / "raw_submissions.json"

# These tables are the structured school-data buckets the bot can answer from.
APPROVED_TABLE_COLUMNS: dict[str, list[str]] = {
    "teachers": [
        "id",
        "full_name",
        "preferred_name",
        "department",
        "email",
        "phone_extension",
        "office_room_id",
        "office_hours",
        "grades_taught",
        "clubs",
        "source_system",
        "source",
        "owner",
        "last_updated",
        "active",
        "is_placeholder",
    ],
    "courses": [
        "id",
        "course_name",
        "course_code",
        "department",
        "level",
        "semester",
        "source_system",
        "source",
        "owner",
        "last_updated",
        "active",
        "is_placeholder",
    ],
    "class_sections": [
        "id",
        "course_id",
        "teacher_id",
        "room_id",
        "period_block",
        "building",
        "floor",
        "semester",
        "source_system",
        "source",
        "owner",
        "last_updated",
        "active",
        "is_placeholder",
    ],
    "rooms": [
        "id",
        "room_number",
        "room_type",
        "assigned_teacher_id",
        "assigned_department",
        "building",
        "wing",
        "floor",
        "nearby_rooms",
        "nearby_landmarks",
        "directions",
        "upstairs_downstairs",
        "needs_pass",
        "common_purpose",
        "source_system",
        "source",
        "owner",
        "last_updated",
        "active",
        "is_placeholder",
    ],
    "office_roles": [
        "id",
        "staff_name",
        "role_title",
        "department",
        "office_location",
        "email",
        "phone_extension",
        "best_contact_method",
        "working_hours",
        "appointment_required",
        "handles",
        "parents_contact_for",
        "not_handle",
        "required_forms",
        "source_system",
        "source",
        "owner",
        "last_updated",
        "active",
        "is_placeholder",
    ],
    "counselors": [
        "id",
        "name",
        "grades_assigned",
        "last_name_split",
        "office_location",
        "email",
        "appointment_link",
        "office_hours",
        "walk_in_hours",
        "help_topics",
        "response_time",
        "assigned_by_grade",
        "assigned_by_last_name",
        "parent_contact_allowed",
        "source_system",
        "source",
        "owner",
        "last_updated",
        "active",
        "is_placeholder",
    ],
    "faq_entries": [
        "id",
        "user_type",
        "category",
        "main_question",
        "alternate_phrasings",
        "short_answer",
        "detailed_answer",
        "contact_person",
        "location",
        "link",
        "owner",
        "source_system",
        "source",
        "last_updated",
        "active",
        "is_placeholder",
    ],
    "news_items": [
        "id",
        "title",
        "summary",
        "publish_date",
        "audience",
        "category",
        "source_url",
        "source_system",
        "external_id",
        "owner",
        "last_updated",
        "active",
        "is_placeholder",
    ],
    "events": [
        "id",
        "title",
        "event_date",
        "start_time",
        "end_time",
        "location",
        "category",
        "audience",
        "summary",
        "details",
        "source_url",
        "source_system",
        "external_id",
        "owner",
        "last_updated",
        "active",
        "is_placeholder",
    ],
    "sports_games": [
        "id",
        "sport_name",
        "team_level",
        "season",
        "coach_name",
        "coach_contact",
        "practice_location",
        "home_game_location",
        "game_date",
        "game_time",
        "opponent",
        "home_away",
        "location",
        "transportation_notes",
        "early_dismissal",
        "result",
        "special_event",
        "ticket_info",
        "livestream_link",
        "source_system",
        "external_id",
        "owner",
        "last_updated",
        "active",
        "is_placeholder",
    ],
}

JSON_FIELDS: dict[str, set[str]] = {
    "teachers": {"grades_taught", "clubs"},
    "rooms": {"nearby_rooms", "nearby_landmarks"},
    "office_roles": {"handles", "parents_contact_for", "not_handle", "required_forms"},
    "counselors": {"grades_assigned", "help_topics"},
    "faq_entries": {"alternate_phrasings"},
    "events": set(),
    "sports_games": {"transportation_notes"},
}

CREATE_TABLE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS raw_submissions (
        id TEXT PRIMARY KEY,
        collector_name TEXT,
        category TEXT,
        target_table TEXT,
        raw_text TEXT NOT NULL,
        status TEXT NOT NULL,
        submitted_at TEXT,
        source_system TEXT,
        payload_json TEXT,
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS teachers (
        id TEXT PRIMARY KEY,
        full_name TEXT NOT NULL,
        preferred_name TEXT,
        department TEXT,
        email TEXT,
        phone_extension TEXT,
        office_room_id TEXT,
        office_hours TEXT,
        grades_taught TEXT,
        clubs TEXT,
        source_system TEXT,
        source TEXT,
        owner TEXT,
        last_updated TEXT,
        active INTEGER DEFAULT 1,
        is_placeholder INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS courses (
        id TEXT PRIMARY KEY,
        course_name TEXT NOT NULL,
        course_code TEXT,
        department TEXT,
        level TEXT,
        semester TEXT,
        source_system TEXT,
        source TEXT,
        owner TEXT,
        last_updated TEXT,
        active INTEGER DEFAULT 1,
        is_placeholder INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS class_sections (
        id TEXT PRIMARY KEY,
        course_id TEXT NOT NULL,
        teacher_id TEXT,
        room_id TEXT,
        period_block TEXT,
        building TEXT,
        floor TEXT,
        semester TEXT,
        source_system TEXT,
        source TEXT,
        owner TEXT,
        last_updated TEXT,
        active INTEGER DEFAULT 1,
        is_placeholder INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rooms (
        id TEXT PRIMARY KEY,
        room_number TEXT NOT NULL,
        room_type TEXT,
        assigned_teacher_id TEXT,
        assigned_department TEXT,
        building TEXT,
        wing TEXT,
        floor TEXT,
        nearby_rooms TEXT,
        nearby_landmarks TEXT,
        directions TEXT,
        upstairs_downstairs TEXT,
        needs_pass INTEGER DEFAULT 0,
        common_purpose TEXT,
        source_system TEXT,
        source TEXT,
        owner TEXT,
        last_updated TEXT,
        active INTEGER DEFAULT 1,
        is_placeholder INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS office_roles (
        id TEXT PRIMARY KEY,
        staff_name TEXT,
        role_title TEXT NOT NULL,
        department TEXT,
        office_location TEXT,
        email TEXT,
        phone_extension TEXT,
        best_contact_method TEXT,
        working_hours TEXT,
        appointment_required INTEGER DEFAULT 0,
        handles TEXT,
        parents_contact_for TEXT,
        not_handle TEXT,
        required_forms TEXT,
        source_system TEXT,
        source TEXT,
        owner TEXT,
        last_updated TEXT,
        active INTEGER DEFAULT 1,
        is_placeholder INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS counselors (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        grades_assigned TEXT,
        last_name_split TEXT,
        office_location TEXT,
        email TEXT,
        appointment_link TEXT,
        office_hours TEXT,
        walk_in_hours TEXT,
        help_topics TEXT,
        response_time TEXT,
        assigned_by_grade INTEGER DEFAULT 0,
        assigned_by_last_name INTEGER DEFAULT 0,
        parent_contact_allowed INTEGER DEFAULT 1,
        source_system TEXT,
        source TEXT,
        owner TEXT,
        last_updated TEXT,
        active INTEGER DEFAULT 1,
        is_placeholder INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS faq_entries (
        id TEXT PRIMARY KEY,
        user_type TEXT,
        category TEXT,
        main_question TEXT NOT NULL,
        alternate_phrasings TEXT,
        short_answer TEXT NOT NULL,
        detailed_answer TEXT,
        contact_person TEXT,
        location TEXT,
        link TEXT,
        owner TEXT,
        source_system TEXT,
        source TEXT,
        last_updated TEXT,
        active INTEGER DEFAULT 1,
        is_placeholder INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS news_items (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        publish_date TEXT,
        audience TEXT,
        category TEXT,
        source_url TEXT,
        source_system TEXT,
        external_id TEXT,
        owner TEXT,
        last_updated TEXT,
        active INTEGER DEFAULT 1,
        is_placeholder INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        event_date TEXT,
        start_time TEXT,
        end_time TEXT,
        location TEXT,
        category TEXT,
        audience TEXT,
        summary TEXT NOT NULL,
        details TEXT,
        source_url TEXT,
        source_system TEXT,
        external_id TEXT,
        owner TEXT,
        last_updated TEXT,
        active INTEGER DEFAULT 1,
        is_placeholder INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sports_games (
        id TEXT PRIMARY KEY,
        sport_name TEXT NOT NULL,
        team_level TEXT,
        season TEXT,
        coach_name TEXT,
        coach_contact TEXT,
        practice_location TEXT,
        home_game_location TEXT,
        game_date TEXT,
        game_time TEXT,
        opponent TEXT,
        home_away TEXT,
        location TEXT,
        transportation_notes TEXT,
        early_dismissal INTEGER DEFAULT 0,
        result TEXT,
        special_event TEXT,
        ticket_info TEXT,
        livestream_link TEXT,
        source_system TEXT,
        external_id TEXT,
        owner TEXT,
        last_updated TEXT,
        active INTEGER DEFAULT 1,
        is_placeholder INTEGER DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_teachers_name ON teachers(full_name)",
    "CREATE INDEX IF NOT EXISTS idx_rooms_number ON rooms(room_number)",
    "CREATE INDEX IF NOT EXISTS idx_courses_name ON courses(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_faq_category ON faq_entries(category)",
    "CREATE INDEX IF NOT EXISTS idx_news_publish_date ON news_items(publish_date)",
    "CREATE INDEX IF NOT EXISTS idx_events_event_date ON events(event_date)",
    "CREATE INDEX IF NOT EXISTS idx_sports_game_date ON sports_games(game_date)",
]


# Bootstrapping reads local JSON files and keeps the SQLite catalog in sync.
def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _serialize_field(table: str, field: str, value: Any) -> Any:
    if field in JSON_FIELDS.get(table, set()):
        if value is None:
            return json.dumps([])
        return json.dumps(value)
    if field in {"active", "is_placeholder", "appointment_required", "needs_pass", "assigned_by_grade", "assigned_by_last_name", "parent_contact_allowed", "early_dismissal"}:
        return 1 if value else 0
    return value


def _deserialize_row(table: str, row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    for field in JSON_FIELDS.get(table, set()):
        raw_value = record.get(field)
        if raw_value:
            try:
                record[field] = json.loads(raw_value)
            except json.JSONDecodeError:
                record[field] = []
        else:
            record[field] = []
    return record


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_catalog_db() -> None:
    with get_connection() as connection:
        for statement in CREATE_TABLE_STATEMENTS:
            connection.execute(statement)
        connection.commit()


def _upsert_rows(connection: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    columns = APPROVED_TABLE_COLUMNS[table]
    placeholders = ", ".join("?" for _ in columns)
    update_assignments = ", ".join(f"{column}=excluded.{column}" for column in columns if column != "id")
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {update_assignments}"
    )

    values = []
    for row in rows:
        values.append(tuple(_serialize_field(table, column, row.get(column)) for column in columns))

    connection.executemany(sql, values)


def _upsert_raw_submissions(connection: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    sql = """
        INSERT INTO raw_submissions (
            id,
            collector_name,
            category,
            target_table,
            raw_text,
            status,
            submitted_at,
            source_system,
            payload_json,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            collector_name=excluded.collector_name,
            category=excluded.category,
            target_table=excluded.target_table,
            raw_text=excluded.raw_text,
            status=excluded.status,
            submitted_at=excluded.submitted_at,
            source_system=excluded.source_system,
            payload_json=excluded.payload_json,
            notes=excluded.notes
    """

    values = []
    for row in rows:
        payload_json = json.dumps(row.get("payload")) if row.get("payload") is not None else None
        values.append(
            (
                row.get("id"),
                row.get("collector_name"),
                row.get("category"),
                row.get("target_table"),
                row.get("raw_text"),
                row.get("status", "pending"),
                row.get("submitted_at"),
                row.get("source_system", "manual"),
                payload_json,
                row.get("notes"),
            )
        )

    connection.executemany(sql, values)


def _approved_payloads(submissions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    approved: dict[str, list[dict[str, Any]]] = {table: [] for table in APPROVED_TABLE_COLUMNS}
    for submission in submissions:
        target_table = submission.get("target_table")
        payload = submission.get("payload")
        if submission.get("status") != "approved" or not target_table or target_table not in approved or not payload:
            continue

        payload = dict(payload)
        payload.setdefault("id", f"{submission['id']}-approved")
        payload.setdefault("source_system", submission.get("source_system", "manual"))
        payload.setdefault("owner", submission.get("collector_name") or "Catalog Team")
        payload.setdefault("source", f"raw_submission:{submission['id']}")
        payload.setdefault("last_updated", submission.get("submitted_at"))
        payload.setdefault("active", True)
        approved[target_table].append(payload)
    return approved


def bootstrap_catalog() -> None:
    ensure_catalog_db()
    seed_data = _read_json(SEED_PATH, {})
    raw_submissions = _read_json(RAW_SUBMISSIONS_PATH, [])

    with get_connection() as connection:
        for table, columns in APPROVED_TABLE_COLUMNS.items():
            _upsert_rows(connection, table, seed_data.get(table, []))
        _upsert_raw_submissions(connection, raw_submissions)
        for table, rows in _approved_payloads(raw_submissions).items():
            _upsert_rows(connection, table, rows)
        connection.commit()


def _query_rows(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    cursor = connection.execute(sql, params)
    return cursor.fetchall()


def get_catalog_summary() -> dict[str, Any]:
    bootstrap_catalog()
    with get_connection() as connection:
        counts = {
            "teachers": connection.execute("SELECT COUNT(*) FROM teachers WHERE active = 1").fetchone()[0],
            "courses": connection.execute("SELECT COUNT(*) FROM courses WHERE active = 1").fetchone()[0],
            "class_sections": connection.execute("SELECT COUNT(*) FROM class_sections WHERE active = 1").fetchone()[0],
            "rooms": connection.execute("SELECT COUNT(*) FROM rooms WHERE active = 1").fetchone()[0],
            "office_roles": connection.execute("SELECT COUNT(*) FROM office_roles WHERE active = 1").fetchone()[0],
            "counselors": connection.execute("SELECT COUNT(*) FROM counselors WHERE active = 1").fetchone()[0],
            "faq_entries": connection.execute("SELECT COUNT(*) FROM faq_entries WHERE active = 1").fetchone()[0],
            "news_items": connection.execute("SELECT COUNT(*) FROM news_items WHERE active = 1").fetchone()[0],
            "events": connection.execute("SELECT COUNT(*) FROM events WHERE active = 1").fetchone()[0],
            "sports_games": connection.execute("SELECT COUNT(*) FROM sports_games WHERE active = 1").fetchone()[0],
            "pending_submissions": connection.execute(
                "SELECT COUNT(*) FROM raw_submissions WHERE status != 'approved'"
            ).fetchone()[0],
        }

        latest_news = [
            _deserialize_row("news_items", row)
            for row in _query_rows(
                connection,
                "SELECT * FROM news_items WHERE active = 1 ORDER BY publish_date DESC, title ASC LIMIT 3",
            )
        ]
        upcoming_events = [
            _deserialize_row("events", row)
            for row in _query_rows(
                connection,
                "SELECT * FROM events WHERE active = 1 ORDER BY event_date ASC, start_time ASC, title ASC LIMIT 5",
            )
        ]
        upcoming_games = [
            _deserialize_row("sports_games", row)
            for row in _query_rows(
                connection,
                "SELECT * FROM sports_games WHERE active = 1 ORDER BY game_date ASC, game_time ASC LIMIT 3",
            )
        ]

    return {
        "counts": counts,
        "latest_news": latest_news,
        "upcoming_events": upcoming_events,
        "upcoming_games": upcoming_games,
    }


def _make_source_note(table: str, record: dict[str, Any]) -> str:
    bits = [f"Catalog table: {table}"]
    if record.get("owner"):
        bits.append(f"Owner: {record['owner']}")
    if record.get("last_updated"):
        bits.append(f"Updated: {record['last_updated']}")
    if record.get("source_system"):
        bits.append(f"Source system: {record['source_system']}")
    if record.get("is_placeholder"):
        bits.append("Starter data only. Replace with approved school data before student use.")
    return " | ".join(bits)


def _resource(
    *,
    resource_id: str,
    title: str,
    category: str,
    summary: str,
    keywords: list[str],
    details: list[str],
    contacts: list[dict[str, Any]] | None,
    source_url: str | None,
    source_note: str,
    is_placeholder: bool = False,
) -> dict[str, Any]:
    return {
        "id": resource_id,
        "title": title,
        "category": category,
        "source_type": "local",
        "summary": summary,
        "keywords": keywords,
        "details": details,
        "contacts": contacts or [],
        "source_url": source_url,
        "source_note": source_note,
        "is_placeholder": is_placeholder,
    }


def load_catalog_resources() -> list[dict[str, Any]]:
    bootstrap_catalog()
    resources: list[dict[str, Any]] = []

    with get_connection() as connection:
        teachers = [_deserialize_row("teachers", row) for row in _query_rows(connection, "SELECT * FROM teachers WHERE active = 1")]
        for teacher in teachers:
            display_name = teacher.get("preferred_name") or teacher["full_name"]
            details = []
            if teacher.get("email"):
                details.append(f"Email: {teacher['email']}")
            if teacher.get("phone_extension"):
                details.append(f"Phone extension: {teacher['phone_extension']}")
            if teacher.get("office_room_id"):
                details.append(f"Office room: {teacher['office_room_id']}")
            if teacher.get("office_hours"):
                details.append(f"Office hours: {teacher['office_hours']}")
            if teacher.get("grades_taught"):
                details.append(f"Grades taught: {', '.join(teacher['grades_taught'])}")
            if teacher.get("clubs"):
                details.append(f"Clubs or activities: {', '.join(teacher['clubs'])}")

            resources.append(
                _resource(
                    resource_id=f"teacher-{teacher['id']}",
                    title=f"Teacher: {display_name}",
                    category="teachers",
                    summary=f"{display_name} is in {teacher.get('department') or 'the school staff'}.",
                    keywords=[
                        teacher["full_name"],
                        teacher.get("preferred_name") or "",
                        teacher.get("department") or "",
                        *(teacher.get("grades_taught") or []),
                        *(teacher.get("clubs") or []),
                    ],
                    details=details,
                    contacts=[
                        {
                            "name": teacher["full_name"],
                            "role": teacher.get("department") or "Teacher",
                            "email": teacher.get("email"),
                            "phone": teacher.get("phone_extension"),
                        }
                    ],
                    source_url=teacher.get("source") if str(teacher.get("source", "")).startswith("http") else None,
                    source_note=_make_source_note("teachers", teacher),
                    is_placeholder=bool(teacher.get("is_placeholder")),
                )
            )

        rooms = [_deserialize_row("rooms", row) for row in _query_rows(connection, "SELECT * FROM rooms WHERE active = 1")]
        for room in rooms:
            details = []
            if room.get("building"):
                details.append(f"Building: {room['building']}")
            if room.get("wing"):
                details.append(f"Wing: {room['wing']}")
            if room.get("floor"):
                details.append(f"Floor: {room['floor']}")
            if room.get("upstairs_downstairs"):
                details.append(f"Upstairs or downstairs: {room['upstairs_downstairs']}")
            if room.get("directions"):
                details.append(f"Directions: {room['directions']}")
            if room.get("nearby_landmarks"):
                details.append(f"Nearby landmarks: {', '.join(room['nearby_landmarks'])}")
            if room.get("nearby_rooms"):
                details.append(f"Nearby rooms: {', '.join(room['nearby_rooms'])}")
            details.append(f"Needs pass or special access: {'Yes' if room.get('needs_pass') else 'No'}")
            if room.get("common_purpose"):
                details.append(f"Common purpose: {room['common_purpose']}")

            resources.append(
                _resource(
                    resource_id=f"room-{room['id']}",
                    title=f"Room: {room['room_number']}",
                    category="rooms",
                    summary=f"{room['room_number']} is a {room.get('room_type') or 'school room'} in {room.get('building') or 'campus'}.",
                    keywords=[
                        room["room_number"],
                        room.get("room_type") or "",
                        room.get("assigned_department") or "",
                        room.get("building") or "",
                        room.get("wing") or "",
                        *(room.get("nearby_landmarks") or []),
                    ],
                    details=details,
                    contacts=[],
                    source_url=room.get("source") if str(room.get("source", "")).startswith("http") else None,
                    source_note=_make_source_note("rooms", room),
                    is_placeholder=bool(room.get("is_placeholder")),
                )
            )

        class_sections = [
            dict(row)
            for row in _query_rows(
                connection,
                """
                SELECT
                    class_sections.*,
                    courses.course_name,
                    courses.course_code,
                    courses.level,
                    teachers.full_name AS teacher_full_name,
                    teachers.preferred_name AS teacher_preferred_name,
                    rooms.room_number
                FROM class_sections
                LEFT JOIN courses ON courses.id = class_sections.course_id
                LEFT JOIN teachers ON teachers.id = class_sections.teacher_id
                LEFT JOIN rooms ON rooms.id = class_sections.room_id
                WHERE class_sections.active = 1
                """,
            )
        ]
        for section in class_sections:
            teacher_name = section.get("teacher_preferred_name") or section.get("teacher_full_name") or "Unassigned teacher"
            course_name = section.get("course_name") or section.get("course_id")
            details = [
                f"Course code: {section.get('course_code') or 'Not set'}",
                f"Teacher: {teacher_name}",
                f"Period or block: {section.get('period_block') or 'Not set'}",
                f"Room: {section.get('room_number') or section.get('room_id') or 'Not set'}",
                f"Building: {section.get('building') or 'Not set'}",
                f"Floor: {section.get('floor') or 'Not set'}",
                f"Semester: {section.get('semester') or section.get('semester') or 'Not set'}",
                f"Level: {section.get('level') or 'Not set'}",
            ]

            resources.append(
                _resource(
                    resource_id=f"class-section-{section['id']}",
                    title=f"Class: {course_name}",
                    category="classes",
                    summary=f"{course_name} is taught by {teacher_name}.",
                    keywords=[
                        course_name or "",
                        section.get("course_code") or "",
                        teacher_name,
                        section.get("period_block") or "",
                        section.get("room_number") or "",
                        section.get("level") or "",
                    ],
                    details=details,
                    contacts=[],
                    source_url=section.get("source") if str(section.get("source", "")).startswith("http") else None,
                    source_note=_make_source_note("class_sections", section),
                    is_placeholder=bool(section.get("is_placeholder")),
                )
            )

        office_roles = [
            _deserialize_row("office_roles", row)
            for row in _query_rows(connection, "SELECT * FROM office_roles WHERE active = 1")
        ]
        for office_role in office_roles:
            details = []
            if office_role.get("office_location"):
                details.append(f"Location: {office_role['office_location']}")
            if office_role.get("working_hours"):
                details.append(f"Working hours: {office_role['working_hours']}")
            if office_role.get("best_contact_method"):
                details.append(f"Best contact method: {office_role['best_contact_method']}")
            details.append(
                f"Appointment required: {'Yes' if office_role.get('appointment_required') else 'No'}"
            )
            if office_role.get("handles"):
                details.append(f"Handles: {', '.join(office_role['handles'])}")
            if office_role.get("parents_contact_for"):
                details.append(f"Parents should contact for: {', '.join(office_role['parents_contact_for'])}")
            if office_role.get("not_handle"):
                details.append(f"Does not handle: {', '.join(office_role['not_handle'])}")
            if office_role.get("required_forms"):
                details.append(f"Required forms or documents: {', '.join(office_role['required_forms'])}")

            resources.append(
                _resource(
                    resource_id=f"office-role-{office_role['id']}",
                    title=f"Office Role: {office_role['role_title']}",
                    category="office administration",
                    summary=f"{office_role['role_title']} helps with school support and office services.",
                    keywords=[
                        office_role["role_title"],
                        office_role.get("staff_name") or "",
                        office_role.get("department") or "",
                        *(office_role.get("handles") or []),
                    ],
                    details=details,
                    contacts=[
                        {
                            "name": office_role.get("staff_name") or office_role["role_title"],
                            "role": office_role["role_title"],
                            "email": office_role.get("email"),
                            "phone": office_role.get("phone_extension"),
                        }
                    ],
                    source_url=office_role.get("source") if str(office_role.get("source", "")).startswith("http") else None,
                    source_note=_make_source_note("office_roles", office_role),
                    is_placeholder=bool(office_role.get("is_placeholder")),
                )
            )

        counselors = [
            _deserialize_row("counselors", row)
            for row in _query_rows(connection, "SELECT * FROM counselors WHERE active = 1")
        ]
        for counselor in counselors:
            details = []
            if counselor.get("grades_assigned"):
                details.append(f"Grades assigned: {', '.join(counselor['grades_assigned'])}")
            if counselor.get("last_name_split"):
                details.append(f"Last name split: {counselor['last_name_split']}")
            if counselor.get("office_location"):
                details.append(f"Office location: {counselor['office_location']}")
            if counselor.get("office_hours"):
                details.append(f"Office hours: {counselor['office_hours']}")
            if counselor.get("walk_in_hours"):
                details.append(f"Walk-in hours: {counselor['walk_in_hours']}")
            if counselor.get("help_topics"):
                details.append(f"Helps with: {', '.join(counselor['help_topics'])}")
            if counselor.get("response_time"):
                details.append(f"Response time: {counselor['response_time']}")

            resources.append(
                _resource(
                    resource_id=f"counselor-{counselor['id']}",
                    title=f"Counselor: {counselor['name']}",
                    category="counseling",
                    summary=f"{counselor['name']} supports student counseling needs.",
                    keywords=[
                        counselor["name"],
                        counselor.get("last_name_split") or "",
                        *(counselor.get("grades_assigned") or []),
                        *(counselor.get("help_topics") or []),
                    ],
                    details=details,
                    contacts=[
                        {
                            "name": counselor["name"],
                            "role": "Counselor",
                            "email": counselor.get("email"),
                            "phone": None,
                        }
                    ],
                    source_url=counselor.get("appointment_link") or (
                        counselor.get("source") if str(counselor.get("source", "")).startswith("http") else None
                    ),
                    source_note=_make_source_note("counselors", counselor),
                    is_placeholder=bool(counselor.get("is_placeholder")),
                )
            )

        faq_entries = [
            _deserialize_row("faq_entries", row)
            for row in _query_rows(connection, "SELECT * FROM faq_entries WHERE active = 1")
        ]
        for faq in faq_entries:
            details = [faq["detailed_answer"]] if faq.get("detailed_answer") else []
            if faq.get("contact_person"):
                details.append(f"Contact person: {faq['contact_person']}")
            if faq.get("location"):
                details.append(f"Location: {faq['location']}")

            resources.append(
                _resource(
                    resource_id=f"faq-{faq['id']}",
                    title=f"FAQ: {faq['main_question']}",
                    category=faq.get("category") or "faq",
                    summary=faq["short_answer"],
                    keywords=[faq["main_question"], *(faq.get("alternate_phrasings") or [])],
                    details=details,
                    contacts=[],
                    source_url=faq.get("link"),
                    source_note=_make_source_note("faq_entries", faq),
                    is_placeholder=bool(faq.get("is_placeholder")),
                )
            )

        news_items = [
            _deserialize_row("news_items", row)
            for row in _query_rows(connection, "SELECT * FROM news_items WHERE active = 1")
        ]
        for news in news_items:
            details = []
            if news.get("publish_date"):
                details.append(f"Publish date: {news['publish_date']}")
            if news.get("audience"):
                details.append(f"Audience: {news['audience']}")
            if news.get("category"):
                details.append(f"Category: {news['category']}")
            details.append(news["summary"])

            resources.append(
                _resource(
                    resource_id=f"news-{news['id']}",
                    title=f"Daily News: {news['title']}",
                    category="daily news",
                    summary=news["summary"],
                    keywords=[news["title"], news.get("category") or "", news.get("audience") or "", "daily news", "announcements"],
                    details=details,
                    contacts=[],
                    source_url=news.get("source_url"),
                    source_note=_make_source_note("news_items", news),
                    is_placeholder=bool(news.get("is_placeholder")),
                )
            )

        events = [
            _deserialize_row("events", row)
            for row in _query_rows(connection, "SELECT * FROM events WHERE active = 1")
        ]
        for event in events:
            details = []
            if event.get("event_date"):
                details.append(f"Date: {event['event_date']}")
            if event.get("start_time"):
                details.append(f"Start time: {event['start_time']}")
            if event.get("end_time"):
                details.append(f"End time: {event['end_time']}")
            if event.get("location"):
                details.append(f"Location: {event['location']}")
            if event.get("audience"):
                details.append(f"Audience: {event['audience']}")
            if event.get("details"):
                details.append(event["details"])

            resources.append(
                _resource(
                    resource_id=f"event-{event['id']}",
                    title=f"Event: {event['title']}",
                    category="events calendar",
                    summary=event["summary"],
                    keywords=[
                        event["title"],
                        event.get("category") or "",
                        event.get("location") or "",
                        event.get("audience") or "",
                        "event",
                        "calendar",
                    ],
                    details=details,
                    contacts=[],
                    source_url=event.get("source_url"),
                    source_note=_make_source_note("events", event),
                    is_placeholder=bool(event.get("is_placeholder")),
                )
            )

        sports_games = [
            _deserialize_row("sports_games", row)
            for row in _query_rows(connection, "SELECT * FROM sports_games WHERE active = 1")
        ]
        for game in sports_games:
            details = [
                f"Date: {game.get('game_date') or 'Not set'}",
                f"Time: {game.get('game_time') or 'Not set'}",
                f"Opponent: {game.get('opponent') or 'Not set'}",
                f"Home or away: {game.get('home_away') or 'Not set'}",
                f"Location: {game.get('location') or game.get('home_game_location') or 'Not set'}",
                f"Coach: {game.get('coach_name') or 'Not set'}",
                f"Early dismissal needed: {'Yes' if game.get('early_dismissal') else 'No'}",
            ]
            if game.get("special_event"):
                details.append(f"Special event: {game['special_event']}")
            if game.get("result"):
                details.append(f"Result: {game['result']}")
            if game.get("transportation_notes"):
                details.append(f"Transportation notes: {', '.join(game['transportation_notes'])}")

            resources.append(
                _resource(
                    resource_id=f"sports-game-{game['id']}",
                    title=f"Sports Game: {game['sport_name']} {game.get('team_level') or ''}".strip(),
                    category="sports calendar",
                    summary=f"{game['sport_name']} {game.get('team_level') or ''} vs {game.get('opponent') or 'TBD'}.".strip(),
                    keywords=[
                        game["sport_name"],
                        game.get("team_level") or "",
                        game.get("season") or "",
                        game.get("opponent") or "",
                        game.get("home_away") or "",
                        "game",
                        "match",
                    ],
                    details=details,
                    contacts=[],
                    source_url=game.get("livestream_link"),
                    source_note=_make_source_note("sports_games", game),
                    is_placeholder=bool(game.get("is_placeholder")),
                )
            )

    return resources
