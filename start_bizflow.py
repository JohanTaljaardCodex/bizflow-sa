import subprocess, sys, time, signal
processes=[]

def start(name, cmd):
    print(f"Starting {name}...")
    p=subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform=="win32" else 0)
    processes.append((name,p)); return p

def shutdown():
    print("\nStopping BizFlow...")
    for name,p in processes:
        if p.poll() is not None: continue
        try:
            if sys.platform=="win32":
                p.send_signal(signal.CTRL_BREAK_EVENT); time.sleep(1)
                if p.poll() is None: p.terminate()
            else: p.terminate()
        except Exception as e: print(f"Could not stop {name}: {e}")

if __name__=="__main__":
    print("\n================================\n           BIZFLOW SA\n================================\n")
    web=start("Dashboard", [sys.executable,"app.py"]); time.sleep(2)
    worker=start("Automation Engine", [sys.executable,"automation_engine.py"])
    print("\nBizFlow is running at http://127.0.0.1:5000\nPress CTRL+C to stop.\n")
    try:
        while True:
            if web.poll() is not None or worker.poll() is not None:
                print("A BizFlow process stopped unexpectedly."); break
            time.sleep(2)
    except KeyboardInterrupt: pass
    finally: shutdown()
