// Request ordering is independent of DOM rendering and provider ownership.
export class NoticeGate {
  constructor(schema) {
    this.schema = schema;
    this.last = null;
  }

  accept(notice) {
    if (notice.schema !== this.schema ||
        typeof notice.runtime_id !== 'string' ||
        !Number.isSafeInteger(notice.state_revision) ||
        notice.state_revision < 1) {
      throw Error('Unsupported update schema');
    }
    if (this.last && notice.runtime_id === this.last.runtime_id &&
        notice.state_revision <= this.last.state_revision) {
      return false;
    }
    this.last = notice;
    return true;
  }
}
