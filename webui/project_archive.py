"""Explicit project backup/restore controls; reruns never submit imports."""
import streamlit as st

from app.services import project_archive as projects


def export_controls(task_id, busy, tr):
    st.divider()
    st.caption(tr('Project Archive Help'))
    if st.button(tr('Prepare Project Download'), disabled=busy, key=f'project_prepare_{task_id}'):
        try:
            with st.spinner(tr('Preparing Project')):
                archive = projects.export_project(task_id)
                try:
                    st.session_state[f'project_archive_{task_id}'] = archive.read_bytes()
                finally:
                    archive.unlink(missing_ok=True)
        except Exception as exc:
            st.error(str(exc))
    saved = st.session_state.get(f'project_archive_{task_id}')
    if saved:
        st.download_button(tr('Download Editable Project'), saved,
            file_name=f'{task_id}.mptproject.zip', mime='application/zip',
            key=f'project_download_{task_id}', on_click='ignore')
        st.caption(tr('Project Snapshot Help'))


def import_controls(tr):
    with st.expander(tr('Import Editable Project')):
        st.caption(tr('Project Import Help'))
        upload = st.file_uploader(tr('Project Archive'), type=['zip'], key='project_import_upload', max_upload_size=512)
        if st.button(tr('Import And Open Project'), disabled=upload is None, key='project_import_submit'):
            try:
                with st.spinner(tr('Validating Project')):
                    task_id = projects.import_project(upload)
            except Exception as exc:
                st.error(str(exc))
            else:
                from webui.editor_workspace import open_editor
                open_editor(task_id)
                st.rerun()
