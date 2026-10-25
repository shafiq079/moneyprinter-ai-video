"""Music/SFX library and selected-clip controls in the dedicated editor."""
import streamlit as st

from app.services import audio_layers as al, webui_task


def render(view, tr):
    task_id, data = view['task_id'], view['audio_draft']
    if data is None:
        st.info(tr('Audio Editor Unavailable'))
        return
    busy = view['busy']
    def queue(action, **changes):
        request = {'action': action, 'expected_revision': view['audio_revision'],
                   'expected_binding': view['audio_binding'], **changes}
        if action in {'apply', 'preview', 'restore'}:
            request['expected_snapshot'] = view['snapshot']
        try:
            webui_task.submit_audio_layers(task_id, request=request)
        except Exception as exc:
            st.error(str(exc))
        else:
            st.toast(tr('Editor Change Queued'))
            st.rerun()
    st.caption(tr('Audio Layers Help'))
    with st.expander(tr('Audio Library'), expanded=not data['clips']):
        upload = st.file_uploader(tr('Upload Music Or SFX'), type=['wav', 'mp3', 'm4a', 'ogg', 'flac'],
                                  max_upload_size=50, key=f'audio_upload_{task_id}', disabled=busy)
        st.caption(tr('Audio Upload Limits'))
        if st.button(tr('Import Audio'), key=f'audio_import_{task_id}', disabled=busy or upload is None):
            queue('upload', content=upload.getvalue(), name=upload.name)
        if view['params'].bgm_type and st.button(tr('Edit Saved Background Music'), key=f'audio_import_base_{task_id}', disabled=busy):
            queue('import_base')
        if data['assets']:
            assets = data['assets']
            selected = st.selectbox(tr('Audio Asset'), list(assets), format_func=lambda key: assets[key]['name'], key=f'audio_asset_{task_id}')
            asset = assets[selected]
            st.audio(str(al.file(task_id, asset['asset'])))
            st.caption(f"{asset['duration_ms'] / 1000:.3f}s")
            kind = st.selectbox(tr('Audio Clip Type'), ['music', 'sfx'], key=f'audio_kind_{task_id}', disabled=busy)
            start = st.number_input(tr('Audio Timeline Start'), min_value=0., max_value=max(0., view['duration'] - .001), value=0., step=.1, key=f'audio_add_start_{task_id}')
            if st.button(tr('Add Audio To Timeline'), key=f'audio_add_{task_id}', disabled=busy or len(data['clips']) >= al.MAX_CLIPS):
                queue('add', asset_id=selected, kind=kind, start_ms=round(start * 1000))
    clips = {c['id']: c for c in data['clips']}
    if clips:
        key = f'audio_selected_{task_id}'
        if st.session_state.get(key) not in clips:
            st.session_state[key] = next(iter(clips))
        labels = {cid: f"{i + 1}. {data['assets'][c['asset_id']]['name']} · {c['kind']}" for i, (cid, c) in enumerate(clips.items())}
        cid = st.selectbox(tr('Audio Clip'), list(clips), format_func=lambda cid: labels[cid], key=key)
        clip = clips[cid]
        st.session_state[f'editor_selected_{task_id}'] = f'audio-{cid}'
        suffix = f"{task_id}_{view['audio_revision']}_{cid}"
        with st.form(f'audio_clip_form_{suffix}'):
            start = st.number_input(tr('Audio Timeline Start'), min_value=0., max_value=3600., value=clip['start_ms'] / 1000, step=.001, format='%.3f')
            begin = st.number_input(tr('Audio Source In'), min_value=0., value=clip['in_ms'] / 1000, step=.001, format='%.3f')
            end = st.number_input(tr('Audio Source Out'), min_value=.001, value=clip['out_ms'] / 1000, step=.001, format='%.3f')
            kind = st.selectbox(tr('Audio Clip Type'), ['music', 'sfx'], index=0 if clip['kind'] == 'music' else 1)
            gain = st.slider(tr('Audio Clip Volume'), 0., 2., float(clip['gain']), .05)
            muted = st.checkbox(tr('Audio Clip Muted'), value=clip['muted'])
            fade_in = st.number_input(tr('Audio Fade In'), min_value=0., value=clip['fade_in_ms'] / 1000, step=.1)
            fade_out = st.number_input(tr('Audio Fade Out'), min_value=0., value=clip['fade_out_ms'] / 1000, step=.1)
            save = st.form_submit_button(tr('Save Audio Clip'), disabled=busy)
        if save:
            queue('update', clip_id=cid, start_ms=round(start * 1000), in_ms=round(begin * 1000), out_ms=round(end * 1000),
                  kind=kind, gain=gain, muted=muted, fade_in_ms=round(fade_in * 1000), fade_out_ms=round(fade_out * 1000))
        if st.button(tr('Duplicate Audio Clip'), key=f'audio_duplicate_{task_id}', disabled=busy or len(clips) >= al.MAX_CLIPS):
            queue('duplicate', clip_id=cid)
        if st.button(tr('Remove Audio Clip'), key=f'audio_remove_{task_id}', disabled=busy):
            queue('remove', clip_id=cid)
    with st.expander(tr('Audio Preview And Export'), expanded=not clips):
        base = st.checkbox(tr('Keep Existing Background Music'), value=data['include_base'], key=f"audio_base_{task_id}_{view['audio_revision']}", disabled=busy)
        if st.button(tr('Save Background Music Choice'), key=f'audio_base_save_{task_id}', disabled=busy):
            queue('base', include_base=base)
        if st.button(tr('Preview Audio Arrangement'), key=f'audio_preview_{task_id}', disabled=busy):
            queue('preview')
        if st.button(tr('Apply Audio And Export'), key=f'audio_apply_{task_id}', disabled=busy):
            queue('apply')
        if st.button(tr('Reset Audio Draft'), key=f'audio_reset_{task_id}', disabled=busy):
            queue('reset')
        if st.button(tr('Restore Original Audio Arrangement'), key=f'audio_restore_{task_id}', disabled=busy or not al.file(task_id, al.ACTIVE).exists()):
            queue('restore')
