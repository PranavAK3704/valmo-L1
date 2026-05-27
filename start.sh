#!/bin/bash
# Free port 8080
python -c "import subprocess; r=subprocess.run(['netstat','-ano'],capture_output=True,text=True,shell=True); [subprocess.run(['taskkill','/PID',l.split()[-1],'/F'],shell=True) for l in r.stdout.split('\n') if ':8080' in l and 'LISTENING' in l]"
# Start
python run_dashboard.py
