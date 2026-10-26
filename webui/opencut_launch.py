"""Open the native OpenCut page from the existing Streamlit task actions."""
import os
import streamlit as st

from app.services import opencut


def launch_url(task_id):
    return '/opencut/#token=' + opencut.ticket(task_id)


def render_launch(task_id, tr):
    st.title('OpenCut video editor')
    if st.button(tr('Back To Generator')):
        from webui.editor_workspace import leave_editor
        leave_editor()
        st.rerun()
    if os.environ.get('MPT_OPENCUT') != '1':
        st.info('Start this branch with sh webui.sh (or webui.bat) to enable OpenCut on the same WebUI address.')
    else:
        st.link_button('Open in OpenCut', launch_url(task_id), type='primary')
    st.caption('OpenCut edits are saved separately. Your generated scenes and the previous editor project stay available.')
    if st.button('Previous editor / generation tools'):
        st.query_params['legacy'] = '1'
        st.rerun()
    root = opencut.directory(task_id)
    for output in sorted((root / 'exports').glob('*')):
        if output.is_file() and output.suffix in {'.mp4', '.webm'}:
            with output.open('rb') as stream:
                st.download_button('Download OpenCut export', stream, file_name=output.name,
                    key='opencut_export_' + output.name, on_click='ignore')
