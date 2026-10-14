const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export async function request<T>(path:string, options:RequestInit = {}):Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData) && options.body) headers.set('Content-Type','application/json');
  let response: Response;
  try {
    response = await fetch(`${API}${path}`,{...options,headers});
  } catch {
    throw new Error('Cannot reach the DocuGuard API. Check that the backend is deployed and VITE_API_URL points to its /api address.');
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(()=>({detail:'The server returned an unreadable response.'}));
  if (!response.ok) throw new Error(data.detail || Object.values(data).flat().join(' ') || 'Request failed.');
  return data as T;
}

export async function download(path:string,name:string){
  const response=await fetch(`${API}${path}`);
  if(!response.ok) throw new Error('Could not download this report.');
  const blob=await response.blob(), url=URL.createObjectURL(blob), a=document.createElement('a'); a.href=url; a.download=name; a.click(); URL.revokeObjectURL(url);
}
