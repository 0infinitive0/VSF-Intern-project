import os
from langsmith import Client
from dotenv import load_dotenv

load_dotenv()
client = Client()

run_id = "019fb694-6867-7e11-9f33-a6a158ff9105"

def print_run(run, indent=0):
    print(" " * indent + f"- Name: {run.name} | Type: {run.run_type}")
    if run.inputs:
        # print(" " * (indent+2) + f"Inputs: {list(run.inputs.keys())}")
        pass
    
    # fetch children
    children = list(client.list_runs(execution_order=run.execution_order, run_type=None, parent_run_id=run.id))
    for child in children:
        print_run(child, indent + 2)

try:
    run = client.read_run(run_id)
    print(f"Loaded Run: {run.name}")
    print_run(run)
except Exception as e:
    print(f"Error: {e}")
