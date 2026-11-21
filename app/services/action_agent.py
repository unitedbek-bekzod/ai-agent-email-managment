import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy import select, desc, or_, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    User, EmailMessage, EmailDraft, UserPreference, FollowUpReminder, AgentAuditLog,
    CategoryEnum, PriorityEnum, ReplyToneEnum
)
from app.services.ai_agent import AIAgentService

logger = logging.getLogger("action_agent")


class ActionAgent:
    """Agentic AI engine that understands natural language commands, selects tools, and executes them."""

    @classmethod
    async def process_user_instruction(
        cls,
        user: User,
        instruction: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Understands user intent, picks tools, executes them, and returns conversational response + tool results."""
        system_prompt = """You are an elite Email Action Agent with tool-calling capabilities.
Based on the user's natural language command, determine the sequence of tools to invoke.
Available Tools:
1. "SEARCH_EMAILS": {"query": str, "sender": str or null, "category": str or null, "priority": str or null, "days_back": int or null}
2. "READ_EMAIL": {"email_id": int}
3. "DRAFT_REPLY": {"email_id": int or null, "sender_name_hint": str or null, "tone": "Professional" | "Friendly" | "Short" | "Detailed" | null}
4. "SET_REMINDER": {"email_id": int or null, "reminder_text": str, "hours": int}
5. "INBOX_SUMMARY": {"category": str or null}
6. "UPDATE_PREFERENCES": {"tone": str or null, "language": str or null, "custom_instructions": str or null}

Output STRICT JSON:
{
  "thought": "Your reasoning about what the user wants to accomplish",
  "tools": [
    {
      "tool_name": "TOOL_NAME",
      "args": {}
    }
  ],
  "response_message": "Friendly explanation to the user in Uzbek about the action taken"
}
"""
        prompt = f"User instruction: {instruction}"

        actions = None
        llm_response = await AIAgentService._call_llm(prompt, system_prompt)
        if llm_response:
            try:
                clean_json = re.sub(r"^```json\s*|\s*```$", "", llm_response.strip(), flags=re.MULTILINE)
                actions = json.loads(clean_json)
            except Exception as e:
                logger.debug(f"[ActionAgent LLM parsing error]: {e}")

        # Fallback heuristic intent planner
        if not actions or "tools" not in actions:
            actions = cls._heuristic_plan(instruction)

        # Execute Planned Tools
        execution_results = []
        for tool_call in actions.get("tools", []):
            tool_name = tool_call.get("tool_name")
            args = tool_call.get("args", {})
            result = await cls._execute_tool(user, tool_name, args, db)
            execution_results.append({
                "tool": tool_name,
                "args": args,
                "result": result
            })

            # Save to Audit Log
            log = AgentAuditLog(
                user_id=user.id,
                tool_name=tool_name,
                arguments_json=json.dumps(args, ensure_ascii=False),
                result_summary=str(result)[:400]
            )
            db.add(log)

        await db.commit()

        # Build response message
        reply_message = actions.get("response_message")
        if not reply_message:
            reply_message = cls._generate_conversational_response(execution_results)

        return {
            "success": True,
            "instruction": instruction,
            "thought": actions.get("thought", "Buyruq tahlil qilindi va bajarildi."),
            "actions_executed": execution_results,
            "response_message": reply_message
        }

    @classmethod
    def _heuristic_plan(cls, text: str) -> Dict[str, Any]:
        """Determines tool sequence when LLM API is unavailable."""
        t = text.lower().strip()
        tools = []
        thought = "Foydalanuvchi buyrug'i matn tahlili orqali aniqlandi."

        if "javob" in t or "draft" in t or "reply" in t:
            # Check tone
            tone = "Professional"
            if "do'stona" in t or "friendly" in t:
                tone = "Friendly"
            elif "qisqa" in t or "short" in t:
                tone = "Short"
            elif "batafsil" in t or "detailed" in t:
                tone = "Detailed"

            # Check sender
            sender_hint = None
            if "sardor" in t:
                sender_hint = "Sardor"
            elif "google" in t:
                sender_hint = "Google"
            elif "alisher" in t:
                sender_hint = "Alisher"

            tools.append({
                "tool_name": "DRAFT_REPLY",
                "args": {"sender_name_hint": sender_hint, "tone": tone}
            })

            if "eslatma" in t or "remind" in t:
                tools.append({
                    "tool_name": "SET_REMINDER",
                    "args": {"reminder_text": "Javob xatini jo'natish", "hours": 24}
                })

        elif "eslatma" in t or "remind" in t:
            tools.append({
                "tool_name": "SET_REMINDER",
                "args": {"reminder_text": text, "hours": 24}
            })

        elif "xulosa" in t or "summary" in t or "dayjest" in t:
            tools.append({
                "tool_name": "INBOX_SUMMARY",
                "args": {}
            })

        elif "sozlama" in t or "til" in t or "ton" in t:
            tools.append({
                "tool_name": "UPDATE_PREFERENCES",
                "args": {}
            })

        else:
            # Default to Search
            tools.append({
                "tool_name": "SEARCH_EMAILS",
                "args": {"query": text}
            })

        return {
            "thought": thought,
            "tools": tools,
            "response_message": ""
        }

    @classmethod
    async def _execute_tool(
        cls,
        user: User,
        tool_name: str,
        args: Dict[str, Any],
        db: AsyncSession
    ) -> Any:
        """Executes a single tool safely and returns structured output."""

        # Tool 1: SEARCH_EMAILS
        if tool_name == "SEARCH_EMAILS":
            query_str = args.get("query", "")
            filters = await AIAgentService.parse_search_query(query_str) if query_str else {}

            # Override with explicit tool args if present
            if args.get("sender"):
                filters["sender"] = args["sender"]
            if args.get("category"):
                filters["category"] = args["category"]
            if args.get("priority"):
                filters["priority"] = args["priority"]

            q = select(EmailMessage).order_by(desc(EmailMessage.received_at))
            if filters.get("category"):
                try:
                    q = q.where(EmailMessage.category == CategoryEnum(filters["category"]))
                except ValueError:
                    pass
            if filters.get("priority"):
                try:
                    q = q.where(EmailMessage.priority == PriorityEnum(filters["priority"]))
                except ValueError:
                    pass
            if filters.get("sender"):
                s = f"%{filters['sender']}%"
                q = q.where(or_(EmailMessage.sender_name.ilike(s), EmailMessage.sender_email.ilike(s)))
            if filters.get("keywords"):
                for w in filters["keywords"].split():
                    k = f"%{w}%"
                    q = q.where(or_(EmailMessage.subject.ilike(k), EmailMessage.body_text.ilike(k)))

            res = await db.execute(q.limit(5))
            emails = res.scalars().all()
            return [
                {
                    "id": e.id,
                    "subject": e.subject,
                    "sender": e.sender_name or e.sender_email,
                    "priority": e.priority.value,
                    "category": e.category.value,
                    "snippet": e.snippet
                }
                for e in emails
            ]

        # Tool 2: READ_EMAIL
        elif tool_name == "READ_EMAIL":
            email_id = args.get("email_id")
            em = (await db.execute(select(EmailMessage).where(EmailMessage.id == email_id))).scalars().first()
            if not em:
                return {"error": "Email topilmadi"}
            return {
                "id": em.id,
                "subject": em.subject,
                "sender": f"{em.sender_name} <{em.sender_email}>",
                "summary": em.summary,
                "key_takeaway": em.key_takeaway,
                "action_items": em.action_items,
                "deadline": em.detected_deadline
            }

        # Tool 3: DRAFT_REPLY
        elif tool_name == "DRAFT_REPLY":
            email_id = args.get("email_id")
            sender_hint = args.get("sender_name_hint")

            em = None
            if email_id:
                em = (await db.execute(select(EmailMessage).where(EmailMessage.id == email_id))).scalars().first()
            elif sender_hint:
                q = select(EmailMessage).where(or_(
                    EmailMessage.sender_name.ilike(f"%{sender_hint}%"),
                    EmailMessage.sender_email.ilike(f"%{sender_hint}%")
                )).order_by(desc(EmailMessage.received_at)).limit(1)
                em = (await db.execute(q)).scalars().first()
            else:
                # Latest email
                q = select(EmailMessage).order_by(desc(EmailMessage.received_at)).limit(1)
                em = (await db.execute(q)).scalars().first()

            if not em:
                return {"error": "Javob tayyorlash uchun mos xat topilmadi."}

            pref = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalars().first()
            tone_str = args.get("tone") or (pref.preferred_tone.value if pref else "Professional")
            tone = ReplyToneEnum(tone_str) if tone_str in [t.value for t in ReplyToneEnum] else ReplyToneEnum.PROFESSIONAL

            draft_body = await AIAgentService.generate_reply(
                subject=em.subject,
                body=em.body_text,
                sender_name=em.sender_name,
                sender_email=em.sender_email,
                tone=tone,
                user_preference=pref
            )

            draft = EmailDraft(
                email_id=em.id,
                tone=tone,
                subject=f"Re: {em.subject}",
                body=draft_body
            )
            db.add(draft)
            await db.flush()

            return {
                "draft_id": draft.id,
                "email_id": em.id,
                "subject": em.subject,
                "sender": em.sender_name,
                "tone": tone.value,
                "draft_text": draft_body
            }

        # Tool 4: SET_REMINDER
        elif tool_name == "SET_REMINDER":
            email_id = args.get("email_id")
            text = args.get("reminder_text", "Email bo'yicha chora ko'rish")
            hours = args.get("hours", 24)

            due = datetime.utcnow() + timedelta(hours=hours)
            rem = FollowUpReminder(
                user_id=user.id,
                email_id=email_id,
                reminder_text=text,
                remind_at=due
            )
            db.add(rem)
            await db.flush()

            return {
                "reminder_id": rem.id,
                "reminder_text": text,
                "remind_at": due.strftime("%Y-%m-%d %H:%M")
            }

        # Tool 5: INBOX_SUMMARY
        elif tool_name == "INBOX_SUMMARY":
            emails = (await db.execute(select(EmailMessage).order_by(desc(EmailMessage.received_at)).limit(10))).scalars().all()
            total = len(emails)
            urgent = sum(1 for e in emails if e.priority == PriorityEnum.URGENT)
            return {
                "total_recent": total,
                "urgent_count": urgent,
                "highlights": [
                    {"subject": e.subject, "priority": e.priority.value, "category": e.category.value, "takeaway": e.key_takeaway}
                    for e in emails[:4]
                ]
            }

        # Tool 6: UPDATE_PREFERENCES
        elif tool_name == "UPDATE_PREFERENCES":
            pref = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalars().first()
            if not pref:
                pref = UserPreference(user_id=user.id)
                db.add(pref)

            if args.get("tone"):
                try:
                    pref.preferred_tone = ReplyToneEnum(args["tone"])
                except ValueError:
                    pass
            if args.get("language"):
                pref.preferred_language = args["language"]
            if args.get("custom_instructions"):
                pref.custom_instructions = args["custom_instructions"]

            await db.flush()
            return {
                "updated_tone": pref.preferred_tone.value,
                "updated_language": pref.preferred_language
            }

        return {"status": "Noma'lum tool chaqirildi"}

    @classmethod
    def _generate_conversational_response(cls, execution_results: List[Dict[str, Any]]) -> str:
        """Constructs human-friendly response describing what the agent executed."""
        if not execution_results:
            return "Buyrug'ingiz qabul qilindi, biroq hech qanday harakat talab etilmadi."

        lines = ["✅ <b>Buyruq muvaffaqiyatli bajarildi:</b>\n"]
        for res in execution_results:
            t = res["tool"]
            r = res["result"]

            if t == "DRAFT_REPLY":
                lines.append(
                    f"✍️ <b>'{r.get('subject')}'</b> xatiga <b>{r.get('tone')}</b> tonda javob draft tayyorlandi.\n"
                    f"<i>Draft: \"{r.get('draft_text', '')[:120]}...\"</i>\n"
                )
            elif t == "SET_REMINDER":
                lines.append(f"⏰ Eslatma o'rnatildi: <b>'{r.get('reminder_text')}'</b> ({r.get('remind_at')} gacha)\n")
            elif t == "SEARCH_EMAILS":
                count = len(r) if isinstance(r, list) else 0
                lines.append(f"🔍 Qidiruv bo'yicha <b>{count} ta</b> mos keluvchi email topildi.\n")
            elif t == "INBOX_SUMMARY":
                lines.append(f"📊 Inbox tahlili: <b>{r.get('total_recent', 0)} ta</b> yangi xat, shulardan <b>{r.get('urgent_count', 0)} tasi</b> shoshilinch.\n")
            elif t == "UPDATE_PREFERENCES":
                lines.append(f"⚙️ Sizning xotira sozlamalaringiz yangilandi ({r.get('updated_tone')}, {r.get('updated_language')}).\n")

        return "\n".join(lines)
