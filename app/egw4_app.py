"""This PC's Tk launcher; grading stays in the fixed f5fed75 engine."""
from datetime import datetime
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / 'private' / 'EGW4-app'
PYTHON = ROOT / 'private' / 'paddle-env' / 'Scripts' / 'python.exe'
EVENT_PREFIX = 'EGW4_EVENT '


class GradingWindow(ttk.Frame):
    def __init__(self, window):
        super().__init__(window, padding=24)
        self.window = window
        self.pack(fill='both', expand=True)
        window.title('English Grammar Workbench · 채점하기')
        window.geometry('800x620')
        window.minsize(800, 620)
        window.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(window)
        style.theme_use('clam')
        style.configure('.', font=('맑은 고딕', 11))
        style.configure('Title.TLabel', font=('맑은 고딕', 20, 'bold'))
        style.configure('Start.TButton', font=('맑은 고딕', 12, 'bold'), padding=10)
        self.columnconfigure(0, weight=1)
        self.books = []
        self.process = None
        self.result_path = None
        self.output = None
        self.events = queue.Queue()
        self.log_lines = []
        self.failed_message = ''
        self.started = None
        self.cancelled = False
        self.student_dir = tk.StringVar()
        self.status = tk.StringVar(value='교재와 학생 스캔 폴더를 고른 뒤 시작하세요.')
        self.detail = tk.StringVar(value='기본 제안안 · 자동확정과 보류를 구분해 보여 줍니다.')
        self.elapsed = tk.StringVar()
        ttk.Label(self, text='객관식 채점', style='Title.TLabel').grid(row=0, sticky='w')
        ttk.Label(self, text='이 PC에 준비된 교재와 로컬 OCR을 사용합니다.').grid(row=1, sticky='w', pady=(4, 20))
        ttk.Label(self, text='1. 교재 선택').grid(row=2, sticky='w')
        self.book = ttk.Combobox(self, state='readonly')
        self.book.grid(row=3, sticky='ew', pady=(6, 6))
        self.book.bind('<<ComboboxSelected>>', self.book_changed)
        self.book_description = tk.StringVar()
        ttk.Label(self, textvariable=self.book_description, wraplength=720).grid(row=4, sticky='w')
        ttk.Label(self, text='준비할 파일: 빈 교재 PDF · 답지 PDF · 기존 교재/쪽 연결 설정\n새 교재 등록은 이 창에서 지원하지 않습니다.', wraplength=720).grid(row=5, sticky='w', pady=(8, 18))
        ttk.Label(self, text='2. 학생 스캔 폴더').grid(row=6, sticky='w')
        folder = ttk.Frame(self)
        folder.grid(row=7, sticky='ew', pady=(6, 6))
        folder.columnconfigure(0, weight=1)
        ttk.Entry(folder, textvariable=self.student_dir, state='readonly').grid(row=0, column=0, sticky='ew')
        self.choose_button = ttk.Button(folder, text='폴더 선택…', command=self.choose_folder)
        self.choose_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(self, text='등록된 스캔 번호와 교재 쪽 연결을 사용합니다. 연결이 모호하면 중단합니다.', wraplength=720).grid(row=8, sticky='w')
        actions = ttk.Frame(self)
        actions.grid(row=9, sticky='ew', pady=18)
        self.start_button = ttk.Button(actions, text='채점 시작', style='Start.TButton', command=self.start)
        self.start_button.pack(side='left')
        self.cancel_button = ttk.Button(actions, text='중단', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=10)
        self.result_button = ttk.Button(actions, text='결과 다시 열기', command=self.open_result, state='disabled')
        self.result_button.pack(side='right')
        ttk.Label(self, textvariable=self.status, wraplength=720).grid(row=10, sticky='w')
        self.progress = ttk.Progressbar(self, mode='determinate', maximum=1)
        self.progress.grid(row=11, sticky='ew', pady=10)
        ttk.Label(self, textvariable=self.detail, wraplength=720).grid(row=12, sticky='w')
        ttk.Label(self, textvariable=self.elapsed).grid(row=13, sticky='w', pady=(8, 0))
        ttk.Label(self, text='결과는 날짜·시간별 새 폴더에 저장됩니다. 보류와 추천 답은 교사가 확인해 주세요.', wraplength=720).grid(row=14, sticky='w', pady=(18, 0))
        self.load_books()
        window.after(150, self.poll)

    def load_books(self):
        errors = []
        for path in sorted((LOCAL / 'books').glob('*.json')):
            try:
                data = json.loads(path.read_text(encoding='utf-8-sig'))
                if not isinstance(data, dict) or not isinstance(data.get('title'), str) or not data['title'].strip():
                    raise ValueError('교재 이름 없음')
                self.books.append((path, data))
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f'{path.name}: {exc}')
        self.book['values'] = [data['title'] for _, data in self.books]
        if self.books:
            self.book.current(0)
            self.book_changed()
        else:
            self.start_button['state'] = 'disabled'
            self.status.set('사용 가능한 교재 설정이 없습니다.')
            self.detail.set('private/EGW4-app/books에 기존 교재 설정이 필요합니다.' + (' 설정 파일 읽기 실패.' if errors else ''))

    def book_changed(self, _event=None):
        if self.book.current() >= 0:
            data = self.books[self.book.current()][1]
            self.book_description.set(data.get('description') or f"등록 범위: 교재 {data.get('page_first', '?')}~{data.get('page_last', '?')}쪽 · {data.get('expected_pages', '?')}쪽 / {data.get('expected_questions', '?')}문항")

    def choose_folder(self):
        folder = filedialog.askdirectory(parent=self.window, title='학생 스캔 JPG가 있는 폴더 선택', mustexist=True)
        if folder:
            self.student_dir.set(folder)

    def start(self):
        if self.process is not None or self.book.current() < 0:
            return
        folder = Path(self.student_dir.get()) if self.student_dir.get() else None
        if folder is None or not folder.is_dir():
            messagebox.showinfo('스캔 폴더 선택', '학생 스캔 폴더를 먼저 선택해 주세요.', parent=self.window)
            return
        if not PYTHON.is_file():
            messagebox.showerror('Python 환경 확인', '이 PC의 기존 Python 환경을 찾을 수 없습니다.\nprivate/paddle-env/Scripts/python.exe를 확인해 주세요.', parent=self.window)
            return
        self.output = LOCAL / 'results' / datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')
        self.output.parent.mkdir(parents=True, exist_ok=True)
        command = [str(PYTHON), '-u', str(ROOT / 'app' / 'egw4_runner.py'), '--book', str(self.books[self.book.current()][0]), '--student-dir', str(folder.resolve()), '--output', str(self.output)]
        try:
            self.process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError as exc:
            messagebox.showerror('실행 실패', str(exc), parent=self.window)
            return
        self.log_lines = []
        self.failed_message = ''
        self.result_path = None
        self.cancelled = False
        self.started = time.monotonic()
        self.start_button['state'] = self.choose_button['state'] = self.book['state'] = 'disabled'
        self.cancel_button['state'] = 'normal'
        self.result_button['state'] = 'disabled'
        self.progress['value'] = 0
        self.status.set('교재와 스캔 연결 확인 중…')
        self.detail.set('완료되면 결과 화면을 기본 브라우저로 엽니다.')
        threading.Thread(target=self.read_worker, args=(self.process,), daemon=True).start()

    def read_worker(self, process):
        for line in process.stdout:
            self.events.put(('line', line))
        process.stdout.close()
        self.events.put(('exit', process.wait()))

    def poll(self):
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'exit':
                self.finished(value)
                continue
            self.log_lines.append(value)
            if not value.startswith(EVENT_PREFIX):
                continue
            try:
                event = json.loads(value[len(EVENT_PREFIX):])
            except ValueError:
                continue
            if event.get('event') == 'complete':
                self.result_path = Path(event['report'])
                summary = event['summary']
                self.status.set(f"완료 · {summary['questions']}문항 / 자동확정 {summary['automatic']} / 보류 {summary['held']} / 추천 {summary['recommendations']}")
                messages = event.get('held_messages') or []
                self.detail.set('\n'.join(messages[:3]) if messages else '보류와 추천 답은 결과 화면에서 근거 이미지를 확인해 주세요.')
                self.progress['value'] = self.progress['maximum']
            elif event.get('event') == 'error':
                self.failed_message = event.get('message', '채점을 완료하지 못했습니다.')
                if event.get('detail'):
                    self.failed_message += '\n' + str(event['detail'])
            else:
                total = event.get('total', 0)
                done = event.get('done', 0)
                if total:
                    self.progress['maximum'] = total
                    self.progress['value'] = done
                message = event.get('message') or event.get('stage', '처리 중')
                if event.get('stage', '').startswith('retry-'):
                    message = '재판독 중입니다.' if '단계가 끝났습니다' in message else '재판독 · ' + message
                self.status.set(message)
                if total:
                    self.detail.set(f'{total}쪽 중 {done}쪽 · 현재 단계 진행 상황')
        if self.process is not None and self.started is not None:
            seconds = int(time.monotonic() - self.started)
            self.elapsed.set(f'경과 시간 {seconds // 60}분 {seconds % 60}초')
        self.window.after(150, self.poll)

    def finished(self, returncode):
        log_error = ''
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            with (self.output / 'EGW4-window.log').open('x', encoding='utf-8') as stream:
                stream.write(''.join(self.log_lines))
        except OSError:
            log_error = ' 실행 기록을 저장하지 못했습니다. 폴더 권한과 디스크 공간을 확인해 주세요.'
        finally:
            self.process = None
            self.start_button['state'] = self.choose_button['state'] = 'normal'
            self.book['state'] = 'readonly'
            self.cancel_button['state'] = 'disabled'
        if returncode == 0 and self.result_path and self.result_path.is_file():
            self.result_button['state'] = 'normal'
            self.open_result()
        else:
            self.status.set('채점을 중단했습니다.' if self.cancelled else self.failed_message or '채점을 완료하지 못했습니다.')
            self.detail.set('이전 결과는 그대로입니다. 이번 실행 기록: ' + str(self.output / 'EGW4-window.log'))
        if log_error:
            self.detail.set(self.detail.get() + log_error)

    def open_result(self):
        if self.result_path and self.result_path.is_file():
            if not webbrowser.open(self.result_path.resolve().as_uri()):
                self.detail.set('브라우저가 열리지 않으면 다음 파일을 직접 열어 주세요: ' + str(self.result_path))

    def cancel(self):
        if self.process is not None and self.process.poll() is None:
            stopped = subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            if stopped.returncode != 0 and self.process.poll() is None:
                self.status.set('작업을 중단하지 못했습니다. 창을 유지한 채 다시 중단해 주세요.')
                return False
            self.cancelled = True
        return True

    def close(self):
        if self.process is not None and self.process.poll() is None:
            if not messagebox.askyesno('진행 중인 채점', '현재 채점을 중단하고 창을 닫을까요?', parent=self.window):
                return
            if not self.cancel():
                return
        self.window.destroy()


if __name__ == '__main__':
    window = tk.Tk()
    try:
        GradingWindow(window)
        window.mainloop()
    except Exception as exc:
        messagebox.showerror('채점 창 실행 실패', '실행 창을 열지 못했습니다.\n' + str(exc), parent=window)
        raise
