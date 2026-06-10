# pyright: reportMissingImports=false
"""
thread_manager.py — 백그라운드 스레드 제어 및 GUI 스레드와의 통신을 위한 스레드 풀 매니저
"""
import traceback
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor

class ThreadManager:
    def __init__(self, root: tk.Tk, max_workers: int = 4):
        self.root = root
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def run_async(self, fn, *args, on_success=None, on_failure=None, **kwargs):
        """
        백그라운드 스레드 풀에서 작업을 비동기적으로 실행하고, 
        작업이 완료되거나 에러가 발생하면 메인 GUI 스레드에서 콜백을 실행합니다.
        """
        def worker():
            try:
                result = fn(*args, **kwargs)
                if on_success:
                    self.root.after(0, on_success, result)
            except Exception as e:
                print(f"[스레드 에러] {e}\n{traceback.format_exc()}")
                if on_failure:
                    self.root.after(0, on_failure, e)
        
        self.executor.submit(worker)

    def shutdown(self, wait=True):
        self.executor.shutdown(wait=wait)
