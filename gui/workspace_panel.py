"""Native management workspace. All I/O runs on workers, widgets on Qt."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,
    QLabel,QPushButton,QListWidget,QListWidgetItem,QStackedWidget,QCheckBox,
    QComboBox,QLineEdit,QPlainTextEdit,QSpinBox,QFileDialog,QInputDialog,
    QMessageBox,QSplitter,QScrollArea)
from gui.theme import C
from gui.style import hud_font
from core import workspace as service
from core.codex_connection import client as codex
from core.browser_bridge import bridge

FLAGS=[
 ('notifications','Desktop notifications','Show task and status notification popups.'),
 ('spoken_alerts','Spoken alerts','Allow unsolicited task/status speech. Normal conversation stays available.'),
 ('browser','Browser connections','Allow paired-profile and Playwright browser commands.'),
 ('computer','Computer control','Allow desktop mouse, keyboard and window tools, subject to OS limits.'),
 ('vision','Screen and camera vision','Allow images for AI analysis. Turning off releases screen sharing and camera preview.'),
 ('apps_open','Open system apps','Allow the app launcher.'),
 ('apps_close','Close system apps','Allow normal close requests; existing unsaved-work safeguards remain.'),
 ('terminal','Terminal commands','Allow shell execution; command confirmations still apply.'),
 ('system_settings','System settings','Allow volume, brightness and network tools.'),
 ('codex','Local Codex connection','Allow local coding threads. Disconnect stops this client, not unrelated Codex clients.'),
 ('tasks','Start background tasks','Allow new tasks. Manage or cancel existing work in Tasks.'),
 ('routines','Run routines','Allow scheduled and manual routines.'),
 ('history','Save activity history','Keep up to 500 local metadata entries; never screenshots or credentials.'),
]

class WorkspaceDialog(QDialog):
    completed=pyqtSignal(str,object,str)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('JARVIS Workspace');self.resize(1100,760);self.setMinimumSize(850,600)
        self.setFont(hud_font(11))
        self.setStyleSheet(f'''
            QDialog,QWidget{{background:{C.PANEL};color:{C.WHITE};}}
            QLineEdit,QPlainTextEdit,QListWidget,QComboBox,QSpinBox{{background:{C.BG};border:1px solid {C.BORDER};padding:7px;selection-background-color:{C.BORDER_B};}}
            QPushButton{{background:{C.PRI_GHO};border:1px solid {C.BORDER_B};padding:8px 12px;border-radius:4px;}}
            QPushButton:hover{{border-color:{C.PRI};}} QPushButton:focus{{border:2px solid {C.PRI};}}
            QPushButton:disabled{{color:{C.TEXT_DIM};}} QListWidget::item{{padding:9px;}}
            QListWidget::item:selected{{background:{C.BORDER};color:{C.WHITE};}}
            QCheckBox{{spacing:10px;padding:5px;}}
            QCheckBox::indicator{{width:18px;height:18px;border:1px solid {C.BORDER_B};border-radius:3px;background:{C.BG};}}
            QCheckBox::indicator:checked{{background:{C.PRI};border-color:{C.PRI};}}
            QScrollArea{{border:0;}}
        ''')
        self._executor=ThreadPoolExecutor(max_workers=4,thread_name_prefix='Workspace')
        self._busy=set();self._callbacks={};self._thread_id='';self._thread_cursor=None
        self._history_cursor=None;self._threads=[];self._task_rows=[];self._routine_rows=[]
        self._seen_events=set();self._approval_ids=[];self._initialized_settings=False
        self.completed.connect(self._finish)
        outer=QVBoxLayout(self);heading=QHBoxLayout()
        title=QLabel('Workspace');title.setFont(hud_font(20));heading.addWidget(title);heading.addStretch()
        close=QPushButton('Close');close.clicked.connect(self.close);heading.addWidget(close);outer.addLayout(heading)
        body=QHBoxLayout();self.nav=QListWidget();self.nav.setFixedWidth(170)
        self.nav.addItems(['Status & access','Browser profiles','Codex threads','Tasks','Routines','Activity history'])
        self.pages=QStackedWidget();body.addWidget(self.nav);body.addWidget(self.pages,1);outer.addLayout(body,1)
        self.footer=QLabel('Ready');self.footer.setTextFormat(Qt.TextFormat.PlainText);self.footer.setWordWrap(True);outer.addWidget(self.footer)
        for factory in (self._status_page,self._browser_page,self._codex_page,self._tasks_page,self._routines_page,self._history_page):self.pages.addWidget(factory())
        self.nav.currentRowChanged.connect(self._page_changed);self.nav.setCurrentRow(0)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(4000)
        self.refresh()

    def _page(self,title,description):
        page=QWidget();layout=QVBoxLayout(page);layout.setSpacing(12)
        header=QLabel(title);header.setFont(hud_font(16));layout.addWidget(header)
        note=QLabel(description);note.setWordWrap(True);note.setStyleSheet(f'color:{C.TEXT_MED};');layout.addWidget(note)
        return page,layout

    def _button(self,layout,text,callback):
        b=QPushButton(text);b.clicked.connect(lambda checked=False:callback());layout.addWidget(b);return b

    def _run(self,tag,fn,callback=None):
        if tag in self._busy:return
        self._busy.add(tag);self._callbacks[tag]=callback
        if not tag.startswith('poll'):self._message('Working…')
        future=self._executor.submit(fn)
        def done(result):
            try:value=result.result();error=''
            except Exception as exc:value=None;error=str(exc)
            self.completed.emit(tag,value,error)
        future.add_done_callback(done)

    def _finish(self,tag,value,error):
        self._busy.discard(tag);callback=self._callbacks.pop(tag,None)
        if error:self._message(error,True);return
        if not tag.startswith('poll'):self._message('Updated')
        if callback:
            try:callback(value)
            except Exception as exc:self._message(str(exc),True);return

    def _message(self,text,error=False):
        self.footer.setText(str(text)[:1000]);self.footer.setStyleSheet(f'color:{C.RED if error else C.TEXT_MED};')

    def _page_changed(self,index):self.pages.setCurrentIndex(index);self.refresh()
    def showEvent(self,event):super().showEvent(event);self.timer.start(4000);self.refresh()
    def closeEvent(self,event):self.timer.stop();super().closeEvent(event)

    def refresh(self):
        index=self.pages.currentIndex()
        if index==0:self._run('poll-status',service.status,self._apply_status)
        elif index==1:self._run('poll-browser',lambda:bridge().snapshot(),self._apply_profiles)
        elif index==2:self._run('poll-codex',lambda:codex().snapshot(),self._apply_codex_status)
        elif index==3:self._run('poll-tasks',service.task_list,self._apply_tasks)
        elif index==4:self._run('poll-routines',lambda:service.routine_engine().list(),self._apply_routines)
        elif index==5:self._run('poll-history',service.history,self._apply_history)

    def _status_page(self):
        page,layout=self._page('Status & access','Switches take effect immediately for new tool calls. Browser and OS permissions remain separate.')
        self.status_summary=QLabel('Checking local status…');self.status_summary.setWordWrap(True);layout.addWidget(self.status_summary)
        scroll=QScrollArea();scroll.setWidgetResizable(True);inner=QWidget();form=QVBoxLayout(inner);self.flags={}
        for key,name,note in FLAGS:
            box=QCheckBox(name);box.setToolTip(note);box.toggled.connect(lambda enabled,k=key:self._set_flag(k,enabled));self.flags[key]=box
            form.addWidget(box);desc=QLabel(note);desc.setWordWrap(True);desc.setStyleSheet(f'color:{C.TEXT_MED};padding-left:27px;');form.addWidget(desc)
        app_form=QFormLayout();self.allowed_apps=QLineEdit();self.allowed_apps.setPlaceholderText('Empty allows any app; otherwise: firefox, calculator')
        app_form.addRow('Allowed app names',self.allowed_apps);form.addLayout(app_form)
        self._button(form,'Save app list',self._save_apps)
        perm_form=QFormLayout();self.tool_name=QLineEdit();self.tool_name.setPlaceholderText('browser_control or terminal_control')
        self.tool_level=QComboBox();self.tool_level.addItems(['allow','ask','deny'])
        perm_form.addRow('Action tool',self.tool_name);perm_form.addRow('Permission',self.tool_level);form.addLayout(perm_form)
        note=QLabel('Ask applies to registered action tools. Use the switches above for screen/camera access.');note.setWordWrap(True);form.addWidget(note)
        self._button(form,'Save tool permission',self._save_tool_permission)
        self.permissions_view=QLabel('');self.permissions_view.setWordWrap(True);form.addWidget(self.permissions_view)
        scroll.setWidget(inner);layout.addWidget(scroll,1);return page

    def _apply_status(self,result):
        cfg=result['settings']
        for key,box in self.flags.items():box.blockSignals(True);box.setChecked(bool(cfg.get(key,True)));box.blockSignals(False)
        if not self._initialized_settings:self.allowed_apps.setText(', '.join(cfg.get('allowed_apps',[])));self._initialized_settings=True
        from memory.config_manager import get_tool_permissions
        self.permissions_view.setText('Tool overrides: '+json.dumps(get_tool_permissions(),ensure_ascii=False))
        connected=sum(p['connected'] for p in result['browser']['profiles'])
        self.status_summary.setText(f"{result['os']} | Browser profiles connected: {connected} | Screen sharing: {'active' if result['screen_sharing'] else 'off'} | Desktop input: {'available' if result['input_available'] else 'OS-limited'}\n"+' '.join(result['notes']))

    def _set_flag(self,key,value):
        self._run('setting-'+key,lambda:service.set_setting(key,value),lambda _:self.refresh())
    def _save_apps(self):
        values=[v.strip() for v in self.allowed_apps.text().split(',') if v.strip()]
        self._run('app-list',lambda:service.set_setting('allowed_apps',values))
    def _save_tool_permission(self):
        name=self.tool_name.text().strip();level=self.tool_level.currentText()
        if not name:self._message('Enter a tool name',True);return
        def save():
            from memory.config_manager import get_tool_permissions,save_tool_permissions
            save_tool_permissions({**get_tool_permissions(),name:level})
        self._run('tool-permission',save,lambda _:self.refresh())

    def _browser_page(self):
        page,layout=self._page('Browser profiles','Pair each real Chrome profile once. Existing accounts remain in Chrome. Only the selected enabled profile receives commands.')
        self.browser_status=QLabel('Bridge not started');layout.addWidget(self.browser_status)
        buttons=QHBoxLayout();self._button(buttons,'Start bridge / new pairing code',self._pair_code)
        self._button(buttons,'Open extension folder',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(__file__).resolve().parent.parent/'browser-extension'))));layout.addLayout(buttons)
        self.pairing=QLineEdit();self.pairing.setReadOnly(True);self.pairing.setPlaceholderText('A pairing code appears here; valid for five minutes');layout.addWidget(self.pairing)
        help_text=QLabel('Chrome → chrome://extensions → Developer mode → Load unpacked → browser-extension. Open the extension in the profile you want, enter its name, bridge port and code, then Pair. Repeat only for profiles you choose. Website access is granted by Chrome.')
        help_text.setWordWrap(True);layout.addWidget(help_text)
        self.profiles=QListWidget();layout.addWidget(self.profiles,1)
        controls=QHBoxLayout()
        self._button(controls,'Use selected profile',self._select_profile)
        self._button(controls,'Enable',lambda:self._profile_change('enable'))
        self._button(controls,'Disable',lambda:self._profile_change('disable'))
        self._button(controls,'Forget profile',lambda:self._profile_change('revoke'))
        layout.addLayout(controls)
        native=QHBoxLayout();self.browser_url=QLineEdit('https://www.google.com');native.addWidget(self.browser_url,1)
        self._button(native,'Use separate JARVIS browser',self._open_browser);layout.addLayout(native)
        return page

    def _pair_code(self):
        def pair():
            service.require('browser');b=bridge();state=b.start()
            if state['error']:raise RuntimeError(state['error'])
            return state,b.new_pairing_code()
        def done(value):
            state,code=value;self.pairing.setText(code);self.browser_status.setText(f"Local bridge: 127.0.0.1:{state['port']} | Pairing code valid for five minutes")
        self._run('pair-code',pair,done)

    def _apply_profiles(self,state):
        selected=self.profiles.currentItem().data(Qt.ItemDataRole.UserRole) if self.profiles.currentItem() else None
        self.profiles.clear()
        for p in state['profiles']:
            status='connected' if p['connected'] else 'disconnected'
            item=QListWidgetItem(f"{p['name']} — {status}; {'enabled' if p['enabled'] else 'disabled'}"+(' [selected]' if p['id']==state['active'] else ''))
            item.setData(Qt.ItemDataRole.UserRole,p['id']);self.profiles.addItem(item)
            if p['id']==selected:self.profiles.setCurrentItem(item)
        if not state['profiles']:self.browser_status.setText('No paired profiles. Create a pairing code to connect one.')
        elif state['running']:self.browser_status.setText(f"Local bridge running on 127.0.0.1:{state['port']}")
        elif state['error']:self.browser_status.setText(state['error'])

    def _profile_id(self):
        item=self.profiles.currentItem()
        if not item:raise ValueError('Select a profile first')
        return item.data(Qt.ItemDataRole.UserRole)
    def _select_profile(self):
        try:pid=self._profile_id()
        except ValueError as exc:self._message(exc,True);return
        self._run('profile-select',lambda:bridge().select(pid),lambda _:self.refresh())
    def _profile_change(self,action):
        try:pid=self._profile_id()
        except ValueError as exc:self._message(exc,True);return
        if action=='revoke' and QMessageBox.question(self,'Forget profile','Remove this profile connection? It must be paired again.')!=QMessageBox.StandardButton.Yes:return
        self._run('profile-change',lambda:bridge().revoke(pid) if action=='revoke' else bridge().enable(pid,action=='enable'),lambda _:self.refresh())
    def _open_browser(self):
        address=self.browser_url.text().strip()
        def launch():
            from actions.browser_control import browser_control
            bridge().select('')
            return browser_control({'action':'go_to','url':address,'browser':'chrome','connection':'playwright'})
        self._run('browser-open',launch,lambda value:self._message(value,'status=failed' in str(value)))

    def _codex_page(self):
        page,layout=self._page('Codex threads','Use your installed local Codex session. Threads have their own history and working directory. Approvals wait for your decision.')
        top=QHBoxLayout();self.codex_state=QLabel('Disconnected');top.addWidget(self.codex_state,1)
        self._button(top,'Connect',self._connect_codex);self._button(top,'Disconnect',lambda:self._run('codex-disconnect',lambda:codex().disconnect(),lambda _:self.refresh()));layout.addLayout(top)
        filters=QHBoxLayout();self.thread_search=QLineEdit();self.thread_search.setPlaceholderText('Search thread titles')
        self.archived=QCheckBox('Archived');self.archived.toggled.connect(lambda _:self._load_threads(False));self.thread_search.returnPressed.connect(lambda:self._load_threads(False));filters.addWidget(self.thread_search,1);filters.addWidget(self.archived)
        self._button(filters,'Refresh',lambda:self._load_threads(False));self.more_threads=self._button(filters,'Load more',lambda:self._load_threads(True));layout.addLayout(filters)
        split=QSplitter();self.thread_list=QListWidget();self.thread_list.currentItemChanged.connect(self._thread_selected);split.addWidget(self.thread_list)
        right=QWidget();right_layout=QVBoxLayout(right);self.thread_details=QLabel('Select a thread to read its saved history');self.thread_details.setTextFormat(Qt.TextFormat.PlainText);self.thread_details.setWordWrap(True);right_layout.addWidget(self.thread_details)
        self.transcript=QPlainTextEdit();self.transcript.setReadOnly(True);right_layout.addWidget(self.transcript,1)
        self._button(right_layout,'Load older messages',self._older_messages)
        self.thread_prompt=QPlainTextEdit();self.thread_prompt.setPlaceholderText('Message for the selected Codex thread');self.thread_prompt.setMaximumHeight(85);right_layout.addWidget(self.thread_prompt)
        actions=QHBoxLayout()
        self._button(actions,'Resume',self._resume_thread);self._button(actions,'Send',self._send_thread);self._button(actions,'Interrupt',self._interrupt_thread);right_layout.addLayout(actions)
        split.addWidget(right);split.setStretchFactor(1,2);layout.addWidget(split,1)
        actions=QHBoxLayout();self._button(actions,'New thread',self._new_thread);self._button(actions,'Rename',self._rename_thread);self._button(actions,'Fork',self._fork_thread);self._button(actions,'Copy resume command',self._copy_resume);self._button(actions,'Archive / restore',self._archive_thread);layout.addLayout(actions)
        self.approvals=QComboBox();layout.addWidget(self.approvals)
        self.approval_details=QPlainTextEdit();self.approval_details.setReadOnly(True);self.approval_details.setMaximumHeight(90);layout.addWidget(self.approval_details)
        self.approvals.currentIndexChanged.connect(self._show_approval)
        decisions=QHBoxLayout();self._button(decisions,'Approve once',lambda:self._decide(True));self._button(decisions,'Deny',lambda:self._decide(False));self._button(decisions,'Answer question',self._answer_question);layout.addLayout(decisions)
        return page

    def _connect_codex(self):
        def connect():codex().connect();return codex().threads()
        self._run('codex-connect',connect,self._threads_loaded)
    def _load_threads(self,more=False):
        query=self.thread_search.text();archived=self.archived.isChecked();cursor=self._thread_cursor if more else None
        if not codex().connected:self._message('Connect to local Codex first',True);return
        self._run('codex-threads',lambda:codex().threads(query,archived,cursor),lambda value:self._threads_loaded(value,more))
    def _threads_loaded(self,value,more=False):
        self._thread_cursor=value.get('nextCursor');self.more_threads.setEnabled(bool(self._thread_cursor))
        self._threads=(self._threads if more else [])+value.get('data',[])
        current=self._thread_id;found=False;self.thread_list.blockSignals(True);self.thread_list.clear()
        for row in self._threads:
            state=(row.get('status') or {}).get('type','unknown');title=row.get('name') or row.get('preview') or row['id']
            item=QListWidgetItem(f"{title[:90]}\n{state} | {row.get('cwd','')}");item.setData(Qt.ItemDataRole.UserRole,row);self.thread_list.addItem(item)
            if row['id']==current:self.thread_list.setCurrentItem(item);found=True
        self.thread_list.blockSignals(False)
        if current and not found:
            self._thread_id='';self.transcript.clear();self.thread_details.setText('Select a thread to read its saved history')
        self.refresh()
    def _thread_selected(self,item,previous=None):
        if not item:return
        row=item.data(Qt.ItemDataRole.UserRole);self._thread_id=row['id'];self._history_cursor=None
        self.thread_details.setText(f"{row.get('name') or row.get('preview') or row['id']}\n{row.get('cwd','')}\n{row['id']}")
        tid=self._thread_id
        self._run('read-'+tid,lambda:codex().read(tid),lambda result:self._show_transcript(tid,result))
    def _show_transcript(self,tid,result,older=False):
        if self._thread_id!=tid:return
        self._history_cursor=result.get('historyCursor')
        text=codex().transcript(result)
        self.transcript.setPlainText((text+'\n\n'+self.transcript.toPlainText()) if older else text)
        self._seen_events={e['time'] for e in codex().snapshot()['events']}
    def _older_messages(self):
        if not self._thread_id or not self._history_cursor:self._message('No older message page is available');return
        tid=self._thread_id;cursor=self._history_cursor
        self._run('older-'+tid,lambda:codex().read(tid,cursor),lambda value:self._show_transcript(tid,value,True))
    def _need_thread(self):
        if not self._thread_id:self._message('Select a Codex thread first',True);return False
        return True
    def _resume_thread(self):
        if not self._need_thread():return
        tid=self._thread_id;self._run('resume-'+tid,lambda:codex().resume(tid),lambda result:self._show_transcript(tid,result))
    def _send_thread(self):
        if not self._need_thread():return
        tid=self._thread_id;text=self.thread_prompt.toPlainText().strip()
        if not text:self._message('Enter a message',True);return
        def send():
            codex().resume(tid)
            return codex().send(tid,text)
        self._run('send-'+tid,send,lambda _:(self.transcript.appendPlainText('\nYou\n'+text+'\n\nCodex\n'),self.thread_prompt.clear()))
    def _interrupt_thread(self):
        if self._need_thread():
            tid=self._thread_id;self._run('interrupt-'+tid,lambda:codex().interrupt(tid))
    def _new_thread(self):
        directory=QFileDialog.getExistingDirectory(self,'Choose project directory')
        if not directory:return
        name,ok=QInputDialog.getText(self,'New thread','Thread name (optional)')
        if not ok:return
        self._run('new-thread',lambda:codex().new(directory,name),self._new_thread_result)
    def _new_thread_result(self,result):
        tid=result['thread']['id'];self._thread_id=tid;self._load_threads()
        self._run('read-'+tid,lambda:codex().read(tid),lambda value:self._show_transcript(tid,value))

    def _rename_thread(self):
        if not self._need_thread():return
        tid=self._thread_id;name,ok=QInputDialog.getText(self,'Rename thread','Name')
        if ok:self._run('rename-thread',lambda:codex().rename(tid,name),lambda _:self._load_threads())
    def _fork_thread(self):
        if self._need_thread():
            tid=self._thread_id;self._run('fork-thread',lambda:codex().fork(tid),self._new_thread_result)
    def _copy_resume(self):
        if self._need_thread():
            import shlex
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText('codex resume '+shlex.quote(self._thread_id))
            self._message('Resume command copied. Run it in a terminal for native Codex controls.')

    def _archive_thread(self):
        if not self._need_thread():return
        tid=self._thread_id;archived=not self.archived.isChecked()
        if QMessageBox.question(self,'Change thread archive','Archive this thread and its children?' if archived else 'Restore this thread?')!=QMessageBox.StandardButton.Yes:return
        self._run('archive-thread',lambda:codex().archive(tid,archived),lambda _:self._load_threads())
    def _apply_codex_status(self,state):
        self.codex_state.setText(('Connected: '+state.get('transport','')) if state['connected'] else ('Disconnected. '+state.get('error','')))
        current=self.approvals.currentData();requests=state['approvals'];self.approvals.blockSignals(True);self.approvals.clear()
        self._approval_ids=requests
        for r in requests:self.approvals.addItem(f"{r['method']} | {r.get('params',{}).get('threadId','')}",r['id'])
        if current is not None:
            index=self.approvals.findData(current)
            if index>=0:self.approvals.setCurrentIndex(index)
        self.approvals.blockSignals(False);self._show_approval()
        for event in state['events']:
            if event['time'] in self._seen_events:continue
            self._seen_events.add(event['time']);params=event.get('params') or {}
            if params.get('threadId')!=self._thread_id:continue
            if event['method']=='item/agentMessage/delta':self.transcript.insertPlainText(params.get('delta',''))
            elif event['method']=='turn/completed':self.transcript.appendPlainText('\n[Turn finished]')
        if len(self._seen_events)>1000:self._seen_events={e['time'] for e in state['events']}
    def _show_approval(self,*args):
        request_id=self.approvals.currentData();request=next((r for r in self._approval_ids if r['id']==request_id),None)
        self.approval_details.setPlainText(json.dumps(request.get('params',{}),indent=2,ensure_ascii=False)[:12000] if request else 'No pending approvals')
    def _decide(self,accept):
        request_id=self.approvals.currentData()
        if request_id is None:return
        if accept and QMessageBox.question(self,'Approve Codex action','Approve the exact action shown above once?')!=QMessageBox.StandardButton.Yes:return
        self._run('approval',lambda:codex().approve(request_id,accept),lambda _:self.refresh())
    def _answer_question(self):
        rid=self.approvals.currentData();request=next((r for r in self._approval_ids if r['id']==rid),None)
        if not request or request['method']!='item/tool/requestUserInput':self._message('Select a user-input request. Other request types remain in the native Codex client.',True);return
        answers={}
        for q in request.get('params',{}).get('questions',[]):
            text,ok=QInputDialog.getText(self,q.get('header') or 'Codex question',q.get('question') or q.get('title') or 'Answer')
            if not ok:return
            answers[q['id']]={'answers':[text]}
        self._run('question-answer',lambda:codex().answer(rid,answers),lambda _:self.refresh())

    def _tasks_page(self):
        page,layout=self._page('Tasks','Add research or general work, inspect results, finish early, or cancel. These use the existing background task engine.')
        form=QFormLayout();self.task_text=QPlainTextEdit();self.task_text.setMaximumHeight(100);form.addRow('Task',self.task_text)
        self.task_agent=QComboBox();self.task_agent.addItems(['general','researcher']);self.task_minutes=QSpinBox();self.task_minutes.setRange(1,720);self.task_minutes.setValue(10)
        form.addRow('Agent',self.task_agent);form.addRow('Budget (minutes)',self.task_minutes);layout.addLayout(form)
        self._button(layout,'Add task',self._add_task);self.task_list=QListWidget();layout.addWidget(self.task_list,1)
        controls=QHBoxLayout();self._button(controls,'Show result',lambda:self._task_action('result'));self._button(controls,'Finish early',lambda:self._task_action('finish'));self._button(controls,'Cancel task',lambda:self._task_action('cancel'));layout.addLayout(controls)
        self.task_result=QPlainTextEdit();self.task_result.setReadOnly(True);self.task_result.setMaximumHeight(150);layout.addWidget(self.task_result);return page
    def _add_task(self):
        text=self.task_text.toPlainText().strip();agent=self.task_agent.currentText();minutes=self.task_minutes.value()
        if not text:self._message('Describe the task',True);return
        self._run('add-task',lambda:service.start_task(text,agent,minutes),lambda _:(self.task_text.clear(),self.refresh()))
    def _apply_tasks(self,rows):
        current=self.task_list.currentItem().data(Qt.ItemDataRole.UserRole) if self.task_list.currentItem() else None
        self.task_list.clear();self._task_rows=rows
        for row in rows:
            item=QListWidgetItem(f"{row.get('title') or row.get('task','')}\n{row.get('status','')} | {row.get('id','')}");item.setData(Qt.ItemDataRole.UserRole,row['id']);self.task_list.addItem(item)
            if row['id']==current:self.task_list.setCurrentItem(item)
    def _task_action(self,action):
        item=self.task_list.currentItem()
        if not item:self._message('Select a task',True);return
        tid=item.data(Qt.ItemDataRole.UserRole)
        if action=='cancel' and QMessageBox.question(self,'Cancel task','Stop this task without a result?')!=QMessageBox.StandardButton.Yes:return
        def done(value):
            if action=='result':self.task_result.setPlainText(str((value or {}).get('result') or (value or {}).get('error') or 'No result yet'))
            self.refresh()
        self._run('task-'+action,lambda:service.task_action(tid,action),done)

    def _routines_page(self):
        page,layout=self._page('Routines','Customize schedules and instructions, pause or resume, and run a routine now. Day numbers: 1 Monday to 7 Sunday.')
        self.routine_list=QListWidget();self.routine_list.setMaximumHeight(150);self.routine_list.currentItemChanged.connect(self._routine_selected);layout.addWidget(self.routine_list)
        form=QFormLayout();self.routine_name=QLineEdit();self.routine_text=QPlainTextEdit();self.routine_text.setMaximumHeight(65)
        self.routine_kind=QComboBox();self.routine_kind.addItems(['prompt','say','task']);self.routine_schedule=QComboBox();self.routine_schedule.addItems(['daily','weekly','monthly','once','interval','startup','idle'])
        self.routine_date=QLineEdit();self.routine_date.setPlaceholderText('YYYY-MM-DD HH:MM for one-off routine');self.routine_monthday=QSpinBox();self.routine_monthday.setRange(1,31);self.routine_between=QLineEdit('00:00-23:59');self.routine_time=QLineEdit('09:00');self.routine_days=QLineEdit('1,2,3,4,5,6,7');self.routine_interval=QSpinBox();self.routine_interval.setRange(1,10080);self.routine_interval.setValue(30)
        self.routine_agent=QComboBox();self.routine_agent.addItems(['general','researcher']);self.routine_budget=QSpinBox();self.routine_budget.setRange(1,720);self.routine_budget.setValue(10)
        self.routine_deliver=QComboBox();self.routine_deliver.addItems(['voice','panel','silent'])
        for label,widget in [('Name',self.routine_name),('Instruction',self.routine_text),('Kind (new routines)',self.routine_kind),('Schedule',self.routine_schedule),('Time HH:MM',self.routine_time),('Once date/time',self.routine_date),('Monthly day',self.routine_monthday),('Interval time window',self.routine_between),('Days 1–7',self.routine_days),('Interval / idle minutes',self.routine_interval),('Task agent',self.routine_agent),('Task budget',self.routine_budget),('Delivery',self.routine_deliver)]:form.addRow(label,widget)
        editor=QWidget();editor.setLayout(form);editor_scroll=QScrollArea();editor_scroll.setWidgetResizable(True);editor_scroll.setWidget(editor);layout.addWidget(editor_scroll,1)
        controls=QHBoxLayout();self._button(controls,'New',self._new_routine);self._button(controls,'Save',self._save_routine);self._button(controls,'Pause / resume',self._toggle_routine);self._button(controls,'Run now',self._run_routine);self._button(controls,'Delete',self._delete_routine);layout.addLayout(controls)
        quiet=QHBoxLayout();self.quiet_hours=QLineEdit();self.quiet_hours.setPlaceholderText('23:00-07:00 or empty to disable');quiet.addWidget(self.quiet_hours,1);self._button(quiet,'Save quiet hours',self._save_quiet);layout.addLayout(quiet);return page
    def _apply_routines(self,rows):
        selected=self.routine_list.currentItem().data(Qt.ItemDataRole.UserRole) if self.routine_list.currentItem() else None
        self.routine_list.blockSignals(True);self.routine_list.clear();self._routine_rows=rows
        for row in rows:
            when=datetime.fromtimestamp(row['next_ts']).strftime('%a %H:%M') if row.get('next_ts') else row.get('trigger',{}).get('type','')
            item=QListWidgetItem(f"{row['name']} | {'on' if row['enabled'] else 'paused'} | {when}");item.setData(Qt.ItemDataRole.UserRole,row['id']);self.routine_list.addItem(item)
            if row['id']==selected:self.routine_list.setCurrentItem(item)
        self.routine_list.blockSignals(False)
    def _routine_selected(self,item,previous=None):
        if not item:return
        rid=item.data(Qt.ItemDataRole.UserRole);row=next(r for r in self._routine_rows if r['id']==rid)
        self.routine_name.setText(row['name']);self.routine_text.setPlainText(row.get('text',''));self.routine_kind.setCurrentText(row['kind'])
        self.routine_agent.setCurrentText(row.get('agent','general'));self.routine_budget.setValue(int(row.get('minutes',10)));self.routine_deliver.setCurrentText(row.get('deliver','voice'))
        trigger=row.get('trigger',{});rule=trigger.get('rule',{})
        schedule=trigger.get('type') if trigger.get('type')!='time' else ('interval' if rule.get('type')=='interval' else 'monthly' if rule.get('type')=='monthly' else 'once' if rule.get('type')=='once' else 'weekly')
        self.routine_monthday.setValue(int(rule.get('day',1)));self.routine_date.setText(datetime.fromtimestamp(rule['at_ts']).strftime('%Y-%m-%d %H:%M') if rule.get('at_ts') else '');self.routine_between.setText(str(rule.get('start','00:00'))+'-'+str(rule.get('end','23:59')))
        self.routine_schedule.setCurrentText(schedule or 'daily');self.routine_time.setText(rule.get('time','09:00'));self.routine_days.setText(','.join(map(str,rule.get('days',[1,2,3,4,5,6,7]))));self.routine_interval.setValue(int(rule.get('minutes') or trigger.get('minutes') or 30))
    def _new_routine(self):
        self.routine_list.clearSelection();self.routine_list.setCurrentItem(None);self.routine_name.clear();self.routine_text.clear()
    def _routine_id(self):
        item=self.routine_list.currentItem();return item.data(Qt.ItemDataRole.UserRole) if item else ''
    def _save_routine(self):
        rid=self._routine_id();schedule=self.routine_schedule.currentText()
        payload={'name':self.routine_name.text(),'text':self.routine_text.toPlainText(),'kind':self.routine_kind.currentText(),'agent':self.routine_agent.currentText(),'minutes':self.routine_budget.value(),'deliver':self.routine_deliver.currentText()}
        if schedule in ('startup','idle'):payload.update(on=schedule,idle_minutes=self.routine_interval.value())
        elif schedule=='interval':payload.update(every_minutes=self.routine_interval.value(),between=self.routine_between.text(),days=self.routine_days.text())
        elif schedule=='monthly':payload.update(monthly_day=self.routine_monthday.value(),time=self.routine_time.text())
        elif schedule=='once':payload.update(at=self.routine_date.text())
        else:payload.update(time=self.routine_time.text(),days=self.routine_days.text() if schedule=='weekly' else '1,2,3,4,5,6,7')
        self._run('routine-save',lambda:service.save_routine(payload,rid),lambda _:self.refresh())
    def _toggle_routine(self):
        rid=self._routine_id()
        if not rid:self._message('Select a routine',True);return
        row=next(r for r in self._routine_rows if r['id']==rid)
        self._run('routine-toggle',lambda:service.routine_engine().update(rid,enabled=not row['enabled']),lambda _:self.refresh())
    def _run_routine(self):
        rid=self._routine_id()
        if rid:self._run('routine-run',lambda:service.routine_engine().run_now(rid),lambda _:self.refresh())
    def _delete_routine(self):
        rid=self._routine_id()
        if not rid:return
        if QMessageBox.question(self,'Delete routine','Delete the selected custom routine? Built-in routines can only be paused.')!=QMessageBox.StandardButton.Yes:return
        self._run('routine-delete',lambda:service.routine_engine().remove(rid),lambda _:self.refresh())
    def _save_quiet(self):
        value=self.quiet_hours.text().strip();self._run('quiet-hours',lambda:service.routine_engine().set_quiet_hours(value))

    def _history_page(self):
        page,layout=self._page('Activity history','Local tool and settings metadata only. Codex conversations stay in Codex; task results stay in the task engine.')
        self.history_list=QListWidget();layout.addWidget(self.history_list,1)
        controls=QHBoxLayout();self._button(controls,'Refresh',self.refresh);self._button(controls,'Clear local activity history',self._clear_history);layout.addLayout(controls);return page
    def _apply_history(self,rows):
        self.history_list.clear()
        for row in rows:self.history_list.addItem(f"{datetime.fromtimestamp(row['time']).strftime('%Y-%m-%d %H:%M:%S')} | {row['kind']} | {row['name']} | {row['status']}")
    def _clear_history(self):
        if QMessageBox.question(self,'Clear activity history','Delete JARVIS activity metadata? Codex conversations and task results are not deleted.')!=QMessageBox.StandardButton.Yes:return
        self._run('clear-history',service.clear_history,lambda _:self.refresh())
