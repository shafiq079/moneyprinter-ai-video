"""Dedicated editor page; the generator and Task Manager remain separate views."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.models.schema import VideoFitMode, VideoTransitionMode
from app.services import caption_edits as ce, generation_manifest as gm, task as tm, webui_task
from app.services import editor_workspace as project

ASSETS = Path(__file__).parent / 'editor_frontend' / 'dist'


def requested_task():
    return st.query_params.get('editor') or st.session_state.get('editor_task_id')


def open_editor(task_id):
    project.task_root(str(task_id))
    st.session_state['editor_task_id'] = str(task_id)
    st.session_state['scene_editor_task_id'] = str(task_id)
    st.session_state['settings_dialog_open'] = False
    st.session_state['task_manager_popover_nonce'] = st.session_state.get('task_manager_popover_nonce', 0) + 1
    st.query_params.clear()
    st.query_params['editor'] = str(task_id)


def leave_editor():
    for key in ('editor_task_id', 'scene_editor_task_id'):
        st.session_state.pop(key, None)
    st.query_params.clear()
    st.query_params['view'] = 'tasks'


@st.cache_resource
def timeline_component():
    return st.components.v2.component('mpt_project_timeline',
        js='// Offline editor workspace\n' + (ASSETS / 'workspace.js').read_text(encoding='utf-8'),
        css='/* Offline editor workspace */\n' + (ASSETS / 'workspace.css').read_text(encoding='utf-8'), isolate_styles=False)


def _labels(tr):
    return {'timeline': tr('Editor Timeline'), 'start': tr('Editor Start'), 'play': tr('Editor Play'),
            'pause': tr('Editor Pause'), 'frameBack': tr('Editor Previous Frame'), 'frameNext': tr('Editor Next Frame'),
            'zoom': tr('Editor Zoom'), 'tracks': tr('Editor Tracks'), 'visual': tr('Editor Clips'),
            'narration': tr('Editor Narration'), 'captions': tr('Editor Captions'), 'music': tr('Editor Music'),
            'draft': tr('Editor Caption Draft'), 'saved': tr('Editor Saved Layout'), 'hint': tr('Editor Timeline Hint'),
            'playError': tr('Editor Play Failed')}


def _css():
    st.html('''<style>
    .stApp{background:#10141b}header[data-testid="stHeader"]{background:#10141b}
    [data-testid="stMainBlockContainer"]{max-width:none;padding:1rem 1.5rem 1rem}
    .st-key-editor_shell{color:#dbe4f1;font-family:Inter,system-ui,sans-serif}
    .st-key-editor_shell h1,.st-key-editor_shell h2,.st-key-editor_shell h3{color:#e3eaf4}
    .st-key-editor_shell [data-testid="stCaptionContainer"]{color:#93a2b8;font-size:12px}
    .st-key-editor_shell [data-testid="stWidgetLabel"] p,.st-key-editor_shell label{color:#b9c6d9}
    .st-key-editor_shell button{background:#252e3d;border-color:#3a4659;color:#dbe6f4;border-radius:6px}
    .st-key-editor_shell button[kind="primary"]{background:#94ecd0;color:#102b24;border-color:#94ecd0}
    .st-key-editor_shell button:disabled{opacity:.45;color:#a1b0c7;background:#1b2330}
    .st-key-editor_shell button[kind="segmented_controlActive"]{background:#203c36;border-color:#80d7bd;color:#b1f7df}
    .st-key-editor_shell button:hover{border-color:#8ce3c9;color:#9ce6d1}
    .st-key-editor_shell input::placeholder{color:#8392a8}
    .st-key-editor_shell input,.st-key-editor_shell textarea,.st-key-editor_shell [data-baseweb="select"]>div{background:#171e29;color:#dbe6f4}
    .st-key-editor_shell [data-testid="stExpander"]{background:#1b2330;border-color:#354154}
    .st-key-editor_shell [data-testid="stExpander"] summary{color:#c7d5e9;background:#1b2330!important}
    .st-key-editor_shell [data-testid="stExpander"] details{background:#1b2330!important}
    .st-key-editor_shell [data-testid="stFileUploaderDropzone"]{background:#1e2735;color:#b9c6d9}
    .st-key-editor_bin,.st-key-editor_inspector{background:#1a212c;border:1px solid #303b4b;border-radius:9px;padding:12px}
    .st-key-editor_program{background:#090c11;border:1px solid #303b4b;border-radius:9px;padding:8px}
    .st-key-editor_program [data-testid="stVideo"]{height:355px}
    .st-key-editor_program video{height:355px!important;width:100%;object-fit:contain;background:#080a0e}
    .st-key-editor_shell [data-testid="stVerticalBlock"]{gap:.65rem}
    .st-key-editor_shell [data-testid="stMarkdownContainer"] p{font-size:12px}
    .st-key-editor_shell [data-testid="stDownloadButton"] button{width:100%}
    .st-key-editor_shell hr{border-color:#303b4b}
    @media(max-width:1000px){[data-testid="stMainBlockContainer"]{padding:1rem}.st-key-editor_program video,.st-key-editor_program [data-testid="stVideo"]{height:280px!important}}
    </style>''')


def _export_panel(view, tr):
    task_id, params = view['task_id'], view['params']
    st.caption(tr('Editor Export Help'))
    with st.form(f'editor_export_{task_id}'):
        size = st.number_input(tr('Font Size'), min_value=1, max_value=200, value=max(1, min(200, params.font_size or 60)))
        voice = st.slider(tr('Voice Volume'), 0.0, 2.0, float(params.voice_volume or 0), 0.05)
        music = st.slider(tr('Background Music Volume'), 0.0, 1.0, min(1.0, float(params.bgm_volume or 0)), 0.05)
        fit = st.selectbox(tr('Video Fit Mode'), ['cover', 'contain'],
                          index=0 if params.video_fit_mode == VideoFitMode.cover else 1)
        transitions = [m.value for m in VideoTransitionMode]
        transition = st.selectbox(tr('Transition Mode'), transitions,
            index=transitions.index(getattr(params.video_transition_mode, 'value', params.video_transition_mode) or 'None'))
        submitted = st.form_submit_button(tr('Editor Render Export'), disabled=view['busy'], type='primary')
    if submitted:
        try:
            proposed = params.model_copy(update={'font_size': int(size), 'voice_volume': voice,
                'bgm_volume': music, 'video_fit_mode': VideoFitMode(fit), 'video_transition_mode': VideoTransitionMode(transition)})
            webui_task.submit_local_ai_rerender(task_id, proposed)
        except Exception as exc:
            st.error(str(exc))
        else:
            st.toast(tr('Editor Export Queued'))
            st.rerun()
    root = project.task_root(task_id)
    for final in sorted(root.glob('final-*.mp4')):
        final = gm.resolve_asset(task_id, final.relative_to(root).as_posix())
        if final.is_file() and final.stat().st_size <= 512 * 1024 * 1024:
            with final.open('rb') as stream:
                st.download_button(tr('Download Video'), stream, file_name=final.name, mime='video/mp4',
                                   key=f'editor_download_{task_id}_{final.name}', on_click='ignore')


def render_editor(task_id, tr, scene_inspector, caption_inspector):
    _css()
    with st.container(key='editor_shell'):
        header = st.columns([1.5, 4.5, 1, 1.3])
        if header[0].button(tr('Editor Back To Tasks'), key='editor_back'):
            leave_editor()
            st.rerun()
        header[1].markdown(f"### {tr('Video Editor')}")
        header[2].button(tr('Refresh'), key='editor_refresh', icon=':material/refresh:')
        if header[3].button(tr('Editor Export'), key='editor_open_export', type='primary'):
            st.session_state['editor_panel'] = 'export'
        busy = tm.is_task_busy(tm.sm.state.get_task(str(task_id)))
        st.session_state[f'editor_polling_{task_id}'] = busy
        content = st.fragment(_render_content, run_every='2s' if busy else None)
        content(task_id, tr, scene_inspector, caption_inspector)


def _render_content(task_id, tr, scene_inspector, caption_inspector):
    try:
        view = project.build_view(str(task_id))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error(f"{tr('Editor Unavailable')}: {exc}")
        return
    if bool(st.session_state.get(f'editor_polling_{task_id}')) != view['busy']:
        st.rerun()
    pending = st.session_state.pop(f'editor_pending_{task_id}', None)
    if pending:
        try:
            result = project.dispatch(task_id, pending, view)
            if 'action' in result:
                action = result['action']
                st.session_state['editor_panel'] = result['panel']
                st.session_state[f'editor_selected_{task_id}'] = action['id']
                st.session_state[f'editor_seek_{task_id}'] = action['start']
                if 'scene_id' in action:
                    st.session_state[f'editor_scene_{task_id}'] = action['scene_id']
                if 'index' in action:
                    st.session_state[f'editor_caption_index_{task_id}'] = action['index']
            else:
                if pending['kind'] == 'caption':
                    st.session_state['editor_panel'] = 'captions'
                    st.session_state[f'editor_caption_index_{task_id}'] = pending['index']
                    st.session_state[f'editor_selected_{task_id}'] = f"caption-{pending['index']}"
                elif 'scene_id' in pending:
                    st.session_state['editor_panel'] = 'visual'
                    st.session_state[f'editor_scene_{task_id}'] = pending['scene_id']
                    st.session_state[f'editor_selected_{task_id}'] = f"scene-{pending['scene_id']}"
                    st.session_state[f'editor_seek_after_job_{task_id}'] = True
                st.toast(tr('Editor Change Queued'))
                st.rerun()
        except (OSError, ValueError, RuntimeError) as exc:
            st.error(str(exc))
    st.session_state['editor_task_id'] = str(task_id)
    st.session_state['scene_editor_task_id'] = str(task_id)
    sid = st.session_state.get(f'editor_scene_{task_id}', view['order'][0])
    if sid not in view['order']:
        sid = view['order'][0]
    scene = next(s for s in view['scenes'] if s['id'] == sid)
    if not view['busy'] and st.session_state.pop(f'editor_seek_after_job_{task_id}', False):
        st.session_state[f'editor_seek_{task_id}'] = scene['start']
    st.caption(f"{view['subject']}  ·  {len(view['scenes'])} {tr('Scenes')}  ·  {view['duration']:.2f}s  ·  {task_id}")
    if view['busy']:
        progress = view['state'].get('progress', 0) or 0
        st.progress(max(0.0, min(1.0, progress / 100)), text=tr('Editor Processing'))
    for error_key in ('caption_edit_error', 'scene_order_error', 'scene_timing_error', 'scene_regeneration_error', 'render_only_rerender_error'):
        if view['state'].get(error_key):
            st.error(str(view['state'][error_key]))
    left, center, right = st.columns([1.25, 4.8, 2.7], gap='small')
    with left, st.container(key='editor_bin', height=435):
        st.markdown(f"**{tr('Editor Media')}**")
        search = st.text_input(tr('Editor Find Scene'), key=f'editor_search_{task_id}', label_visibility='collapsed', placeholder=tr('Editor Find Scene'))
        matching = [s for s in view['scenes'] if search.lower() in s['label'].lower() or search == str(s['id'])]
        pages = max(1, (len(matching) + 11) // 12)
        page = st.number_input(tr('Editor Media Page'), min_value=1, max_value=pages, value=1, key=f'editor_media_page_{task_id}_{search}') if pages > 1 else 1
        for item in matching[(page - 1) * 12:page * 12]:
            if item['ready']:
                try:
                    thumb = project.thumbnail(task_id, item['asset'])
                except (OSError, ValueError):
                    thumb = None
                if thumb:
                    st.image(thumb, width='stretch')
            if st.button(f"{tr('Scene')} {item['id']} · {item['duration']:.2f}s", key=f'editor_media_{task_id}_{item["id"]}',
                         type='primary' if sid == item['id'] else 'secondary', use_container_width=True):
                st.session_state[f'editor_scene_{task_id}'] = item['id']
                st.session_state['editor_panel'] = 'visual'
                st.session_state[f'editor_selected_{task_id}'] = f'scene-{item["id"]}'
                st.session_state[f'editor_seek_{task_id}'] = item['start']
                st.rerun()
            st.caption(item['label'][:100] if item['ready'] else tr('Editor Clip Missing'))
    preview = None
    if view['binding']:
        preview = ce.load_preview(task_id, view['binding'], round(view['duration'] * 1000),
                                  view['snapshot'], ce.render_signature(view['params']))
    with center:
        sources = {'program': tr('Editor Program'), 'clip': tr('Editor Selected Clip')}
        if preview:
            sources['captions'] = tr('Editor Caption Preview')
            if st.session_state.get(f'editor_preview_seen_{task_id}') != preview['preview_sha256']:
                st.session_state[f'editor_source_{task_id}'] = 'captions'
                st.session_state[f'editor_preview_seen_{task_id}'] = preview['preview_sha256']
        key = f'editor_source_{task_id}'
        if st.session_state.get(key) not in sources:
            st.session_state[key] = 'program'
        source_kind = st.segmented_control(tr('Editor Preview'), list(sources), format_func=lambda v: sources[v],
                                           key=key, selection_mode='single', required=True, label_visibility='collapsed')
        with st.container(key='editor_program'):
            if source_kind == 'captions':
                path = gm.resolve_asset(task_id, preview['preview_asset'])
                st.caption(tr('Caption Preview Help'))
            elif source_kind == 'clip' and scene['asset']:
                path = gm.resolve_asset(task_id, scene['asset'])
            else:
                path = gm.resolve_asset(task_id, 'final-1.mp4')
            if path.is_file():
                start = st.session_state.get(f'editor_seek_{task_id}', 0) if source_kind != 'clip' else 0
                st.video(str(path), start_time=max(0.0, float(start)))
            else:
                st.info(tr('Editor Preview Missing'))
        st.caption(tr('Editor Source Status').format(version=scene['version'], scene=sid))
    with right, st.container(key='editor_inspector', height=435):
        panels = {'visual': tr('Editor Clips'), 'narration': tr('Editor Narration'),
                  'captions': tr('Editor Captions'), 'export': tr('Editor Export')}
        if st.session_state.get('editor_panel') not in panels:
            st.session_state['editor_panel'] = 'visual'
        panel = st.segmented_control(tr('Editor Inspector'), list(panels), format_func=lambda v: panels[v],
                                     key='editor_panel', selection_mode='single', required=True, label_visibility='collapsed')
        if panel in {'visual', 'narration'}:
            scene_inspector(workspace=True, scene_id_filter=sid, panel=panel)
        elif panel == 'captions':
            cue_key = f'caption_selected_{task_id}_{view["caption_revision"]}'
            if view['caption_draft'] and view['rows'][2]['actions'] and cue_key not in st.session_state:
                st.session_state[cue_key] = min(st.session_state.get(f'editor_caption_index_{task_id}', 0), len(view['rows'][2]['actions']) - 1)
            caption_inspector(workspace=True)
            if cue_key in st.session_state:
                index = st.session_state[cue_key]
                st.session_state[f'editor_caption_index_{task_id}'] = index
                st.session_state[f'editor_selected_{task_id}'] = f'caption-{index}'
        else:
            _export_panel(view, tr)
    payload = {k: view[k] for k in ('task_id', 'rows', 'duration', 'extent', 'revision', 'busy')}
    payload.update(selected=st.session_state.get(f'editor_selected_{task_id}', f'scene-{sid}'),
                   labels=_labels(tr), captionDraft=view['caption_draft'], playbackOffset=scene['start'] if source_kind == 'clip' else 0)
    event = timeline_component()(key=f'editor_timeline_{task_id}', data=payload, on_event_change=lambda: None).event
    if isinstance(event, dict) and isinstance(event.get('nonce'), str) and event['nonce'] != st.session_state.get(f'editor_event_seen_{task_id}'):
        st.session_state[f'editor_event_seen_{task_id}'] = event['nonce']
        st.session_state[f'editor_pending_{task_id}'] = event
        st.rerun()
    if not view['exact']:
        st.caption(tr('Editor Legacy Layout Help'))
