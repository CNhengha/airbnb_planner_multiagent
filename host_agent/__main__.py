import json
import asyncio
import traceback  # Import the traceback module
import json
import datetime
import os
from collections.abc import AsyncIterator
from pprint import pformat

import gradio as gr

from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from routing_agent import (
    root_agent as routing_agent,
)


APP_NAME = 'routing_app'
USER_ID = 'default_user'
SESSION_ID = 'default_session'

SESSION_SERVICE = InMemorySessionService()
ROUTING_AGENT_RUNNER = Runner(
    agent=routing_agent,
    app_name=APP_NAME,
    session_service=SESSION_SERVICE,
)
LOG_PATH = "/mnt/ssd2/dh/Agent/logs/session_trace.log"
LOGPATH = "/mnt/ssd2/dh/Agent/logs/prompt_debug.log"
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
def log_json(obj, header=""):
    """简单的 JSON 打印/记录函数"""
    import json, os
    os.makedirs(os.path.dirname(LOGPATH), exist_ok=True)
    with open(LOGPATH, "a", encoding="utf-8") as f:
        f.write(f"\n=== {header} @ {datetime.datetime.now().isoformat()} ===\n")
        try:
            import dataclasses
            if hasattr(obj, "model_dump"):
                f.write(json.dumps(obj.model_dump(exclude_none=True), indent=2, ensure_ascii=False))
            else:
                f.write(json.dumps(obj, indent=2, ensure_ascii=False))
        except Exception:
            f.write(str(obj))
        f.write("\n------------------------------------\n")

def log_event(user_message: str, event_obj: object):
    """记录单个事件到日志文件"""
    try:
        timestamp = datetime.now().isoformat()
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n=== New Event @ {timestamp} ===\n")
            f.write(f"User Message: {user_message}\n")
            if event_obj:
                try:
                    json_data = event_obj.model_dump(exclude_none=True)
                except Exception:
                    json_data = str(event_obj)
                f.write(json.dumps(json_data, indent=2, ensure_ascii=False))
                f.write("\n---------------------------------------\n")
    except Exception as e:
        print(f"[LOG ERROR] Failed to write event log: {e}")

"""
async def get_response_from_agent(
    message: str,
    history: list[gr.ChatMessage],
) -> AsyncIterator[gr.ChatMessage]:
    try:
        print(f"[DEBUG] Runner.run_async() called with message: {message}")
        ctx = await SESSION_SERVICE.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID)
        prompt_text = routing_agent.instruction(ctx)
        log_json({"system_prompt": prompt_text, "user_message": message}, header="MODEL PROMPT")
        event_iterator: AsyncIterator[Event] = ROUTING_AGENT_RUNNER.run_async(
            user_id=USER_ID,    
            session_id=SESSION_ID,
            new_message=types.Content(
                role='user', parts=[types.Part(text=message)]
            ),
        )

        async for event in event_iterator:
            log_event(message, event)
            log_json(event, header="MODEL RESPONSE EVENT")
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.function_call:
                        formatted_call = f'```python\n{pformat(part.function_call.model_dump(exclude_none=True), indent=2, width=80)}\n```'
                        yield gr.ChatMessage(
                            role='assistant',
                            content=f'🛠️ **Tool Call: {part.function_call.name}**\n{formatted_call}',
                        )
                    elif part.function_response:
                        response_content = part.function_response.response
                        if (
                            isinstance(response_content, dict)
                            and 'response' in response_content
                        ):
                            formatted_response_data = response_content[
                                'response'
                            ]
                        else:
                            formatted_response_data = response_content
                        formatted_response = f'```json\n{pformat(formatted_response_data, indent=2, width=80)}\n```'
                        yield gr.ChatMessage(
                            role='assistant',
                            content=f'⚡ **Tool Response from {part.function_response.name}**\n{formatted_response}',
                        )
            if event.is_final_response():
                final_response_text = ''
                if event.content and event.content.parts:
                    final_response_text = ''.join(
                        [p.text for p in event.content.parts if p.text]
                    )
                elif event.actions and event.actions.escalate:
                    final_response_text = f'Agent escalated: {event.error_message or "No specific message."}'
                if final_response_text:
                    yield gr.ChatMessage(
                        role='assistant', content=final_response_text
                    )
                break
    except Exception as e:
        print(f'Error in get_response_from_agent (Type: {type(e)}): {e}')
        traceback.print_exc()  # This will print the full traceback
        yield gr.ChatMessage(
            role='assistant',
            content='An error occurred while processing your request. Please check the server logs for details.',
        )
"""
import json, os, time, datetime, traceback
from pprint import pformat
import gradio as gr
from typing import AsyncIterator
from google.genai import types
from google.adk.events import Event

LOG_DIR = "./logs"
os.makedirs(LOG_DIR, exist_ok=True)
SESSION_LOG = os.path.join(LOG_DIR, f"session_{datetime.date.today()}.log")

def write_log(data: dict, header: str = None):
    """Append structured data to daily log file."""
    with open(SESSION_LOG, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 100 + "\n")
        if header:
            f.write(f"=== {header} @ {datetime.datetime.now()} ===\n")
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n" + "=" * 100 + "\n")

async def get_response_from_agent(
    message: str,
    history: list[gr.ChatMessage],
) -> AsyncIterator[gr.ChatMessage]:
    """Get response from host agent and log full runtime info."""

    start_time = time.time()
    runtime_record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "user_message": message,
        "events": [],
        "final_response": None,
        "error": None,
    }

    try:
        print(f"[DEBUG] Runner.run_async() called with message: {message}")
        ctx = await SESSION_SERVICE.get_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
        )
        prompt_text = routing_agent.instruction(ctx)
        write_log({"system_prompt": prompt_text, "user_message": message}, "MODEL PROMPT")

        event_iterator: AsyncIterator[Event] = ROUTING_AGENT_RUNNER.run_async(
            user_id=USER_ID,
            session_id=SESSION_ID,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        )

        async for event in event_iterator:
            # --- 记录事件
            runtime_record["events"].append({
                "time": time.time(),
                "event_type": event.type if hasattr(event, "type") else "unknown",
                "content": str(event.content)[:300] if event.content else None,
            })
            log_json(event, header="MODEL RESPONSE EVENT")

            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.function_call:
                        formatted_call = f"```python\n{pformat(part.function_call.model_dump(exclude_none=True), indent=2, width=80)}\n```"
                        yield gr.ChatMessage(
                            role="assistant",
                            content=f"🛠️ **Tool Call: {part.function_call.name}**\n{formatted_call}",
                        )

                    elif part.function_response:
                        response_content = part.function_response.response
                        if isinstance(response_content, dict) and "response" in response_content:
                            formatted_response_data = response_content["response"]
                        else:
                            formatted_response_data = response_content
                        formatted_response = f"```json\n{pformat(formatted_response_data, indent=2, width=80)}\n```"
                        yield gr.ChatMessage(
                            role="assistant",
                            content=f"⚡ **Tool Response from {part.function_response.name}**\n{formatted_response}",
                        )

            # --- 最终响应阶段
            if event.is_final_response():
                final_response_text = ""
                if event.content and event.content.parts:
                    final_response_text = "".join(
                        [p.text for p in event.content.parts if p.text]
                    )
                elif event.actions and event.actions.escalate:
                    final_response_text = f"Agent escalated: {event.error_message or 'No specific message.'}"

                runtime_record["final_response"] = final_response_text
                if final_response_text:
                    yield gr.ChatMessage(role="assistant", content=final_response_text)
                break

    except Exception as e:
        runtime_record["error"] = str(e)
        print(f"❌ Error in get_response_from_agent (Type: {type(e)}): {e}")
        traceback.print_exc()
        yield gr.ChatMessage(
            role="assistant",
            content="An error occurred while processing your request. Please check the server logs for details.",
        )

    finally:
        runtime_record["duration_sec"] = round(time.time() - start_time, 3)
        runtime_record["status"] = "completed" if not runtime_record["error"] else "error"
        write_log(runtime_record, "SESSION SUMMARY")

async def main():
    """Main gradio app."""
    print('Creating ADK session...')
    await SESSION_SERVICE.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
    )
    print('ADK session created successfully.')

    with gr.Blocks(
        theme=gr.themes.Ocean(), title='A2A Host Agent with Logo'
    ) as demo:
        gr.Image(
            '../assets/a2a-logo-black.svg',
            width=100,
            height=100,
            scale=0,
            show_label=False,
            show_download_button=False,
            container=False,
            show_fullscreen_button=False,
        )
        gr.ChatInterface(
            get_response_from_agent,
            title='A2A Host Agent',
            description='This assistant can help you to check weather and find airbnb accommodation',
        )

    print('Launching Gradio interface...')
    demo.queue().launch(
        server_name='0.0.0.0',
        server_port=8083,
    )
    print('Gradio application has been shut down.')


if __name__ == '__main__':
    asyncio.run(main())
