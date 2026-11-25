import threading, webbrowser, os
import uvicorn
from webapp.server import app,TOKEN
if __name__=='__main__':
    port=int(os.environ.get('RESEARCH_PORT','8765'))
    url=f'http://127.0.0.1:{port}/#token={TOKEN}'
    print('Open the local interface:',url,flush=True)
    threading.Timer(1,lambda:webbrowser.open(url)).start()
    uvicorn.run(app,host='127.0.0.1',port=port,access_log=False)
