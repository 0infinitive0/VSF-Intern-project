import os
import json
from langsmith import Client
os.environ['LANGSMITH_API_KEY'] = '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'
client = Client()
try:
    for offset in range(0, 1000, 100):
        runs = list(client.list_runs(project_name='vsf-intern', limit=100, offset=offset))
        for r in runs:
            # extra contains metadata in some versions, in others it's just r.extra
            thread_id = r.extra.get('metadata', {}).get('thread_id', '') if r.extra else ''
            if thread_id == 'b44d6afe-e9fb-476f-8bec-c583fd123cc2' and r.name == 'LangGraph':
                children = list(client.list_runs(trace_id=r.id))
                tools = [c for c in children if c.run_type == 'tool']
                llms = [c for c in children if c.run_type == 'llm']
                print(f'Trace ID: {r.id}, Tools called: {len(tools)}, LLMs called: {len(llms)}')
                if len(llms) > 0:
                    print(f'LLM Inputs: {json.dumps(llms[0].inputs, ensure_ascii=False)[:1000]}...')
                for idx, t in enumerate(tools):
                    print(f'  Tool: {t.name}')
                    print(f'  Inputs: {json.dumps(t.inputs, ensure_ascii=False)}')
                    print(f'  Outputs: {str(t.outputs)[:200]}')
                print('-' * 40)
except Exception as e:
    print(f'Error: {e}')
