const STORE_KEY = 'oneword-edition-v1';
const DB_NAME = 'oneword-edition';

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore('state');
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function loadState() {
  try {
    const dbh = await openDB();
    const data = await new Promise((resolve, reject) => {
      const rq = dbh.transaction('state', 'readonly').objectStore('state').get(STORE_KEY);
      rq.onsuccess = () => resolve(rq.result);
      rq.onerror = () => reject(rq.error);
    });
    dbh.close();
    if (data) return data;
  } catch (e) { /* IndexedDB 不可用时回退读旧 localStorage */ }
  try { return JSON.parse(localStorage.getItem(STORE_KEY)) || { records: [] }; }
  catch { return { records: [] }; }
}

async function saveState(data) {
  const dbh = await openDB();
  await new Promise((resolve, reject) => {
    const tx = dbh.transaction('state', 'readwrite');
    tx.objectStore('state').put(data, STORE_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
  dbh.close();
  try { localStorage.removeItem(STORE_KEY); } catch (e) { /* 迁移清理失败不影响保存 */ }
}