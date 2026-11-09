/* Kullanıcının seçtiği temayı sayfa çizilmeden uygula (yanıp sönmeyi önler). */
try {
  var t = localStorage.getItem('theme');
  if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;
} catch (e) { /* depolama kapalı olabilir */ }
