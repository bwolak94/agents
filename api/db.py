"""
Central DB module registry.

Routers import this module as ``import api.db as _db`` so test patches on
``api.db.X`` are effective (attribute lookup on the module object at call time).

``ALL_DB_MODULES`` and ``INDEXABLE_DB_MODULES`` are used by server.py lifespan
so both lists stay in sync automatically when new modules are added here.
"""
from db import memory as memory_db
from db import analytics as analytics_db
from db import idempotency as idempotency_db
from db import prompts as prompts_db
from db import feedback as feedback_db
from db import rag as rag_db
from db import file_versions as file_versions_db
from db import cache as cache_db
from db import personas as personas_db
from db import tags as tags_db
from db import agent_checkpoints as agent_checkpoints_db
from db import collab_graph as collab_graph_db
from db import macros as macros_db
from db import batch as batch_db
from db import workflows as workflows_db
from db import experiments as experiments_db
from db import prompt_versions as prompt_versions_db
from db import tenants as tenants_db
from db import memory_graph as memory_graph_db
from db import webhooks as webhooks_db
from db import webhook_triggers as webhook_triggers_db
from db import comments as comments_db
from db import session_roles as session_roles_db
from db import request_log as request_log_db
from db import insights as insights_db
from db import plugins as plugins_db
from db import scheduled_reports as scheduled_reports_db

from db.history import (
    init_db,
    load_history,
    clear_history as db_clear_history,
    list_sessions as db_list_sessions,
    load_context,
    set_session_title,
    add_auto_tags,
    get_session_title,
)

# ── Module registries used by server.py lifespan ──────────────────────────────
# Every module that needs set_db() called:
ALL_DB_MODULES = (
    memory_db, analytics_db, idempotency_db, prompts_db, feedback_db,
    rag_db, file_versions_db, cache_db, personas_db,
    tags_db, agent_checkpoints_db, collab_graph_db,
    macros_db, batch_db, workflows_db, experiments_db,
    prompt_versions_db, tenants_db, memory_graph_db, webhooks_db,
    webhook_triggers_db, comments_db, session_roles_db,
    request_log_db, insights_db, plugins_db, scheduled_reports_db,
)

# Subset that also implement ensure_indexes():
INDEXABLE_DB_MODULES = (
    feedback_db, rag_db, file_versions_db, cache_db, personas_db,
    tags_db, agent_checkpoints_db, collab_graph_db, macros_db, batch_db,
    workflows_db, experiments_db, prompt_versions_db, tenants_db,
    memory_graph_db, webhooks_db, webhook_triggers_db, comments_db,
    session_roles_db, request_log_db, insights_db, plugins_db,
    scheduled_reports_db,
    analytics_db,  # D11 — TTL index
    idempotency_db,  # B3 — idempotency TTL
)
