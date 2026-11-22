/* Stable identities survive compatible changes, including missing observations. */
(function (root) {
  const state = {
    select(items, key, field='id') { return items.find(item => item[field] === key) || null; },
    banner(previous, degraded) {
      return {degraded, dismissed: degraded && previous.degraded ? previous.dismissed : false};
    },
    saved(caseRow, selectedBook, signal) {
      return {version:1, caseKey:caseRow.key, auditId:caseRow.id, exportHash:caseRow.export_sha256, selectedBook, signal};
    },
    verifySaved(saved, cases) {
      const row = cases.find(c => c.key === saved.caseKey);
      if (saved.version !== 1 || !row || row.id !== saved.auditId || row.export_sha256 !== saved.exportHash)
        throw new Error('Saved audit identity is unavailable or changed. Selection retained; no replacement opened.');
      return row;
    }
  };
  if (typeof module !== 'undefined') module.exports=state;
  root.E5State=state;
})(globalThis);
