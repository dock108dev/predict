'use strict';
// Inherit the offline boundary in browser tests and their child Node processes.
const fs = require('node:fs');
const path = require('node:path');
const {fileURLToPath} = require('node:url');
const root = process.env.PREDICT_CI_ISOLATED_ROOT ? fs.realpathSync(process.env.PREDICT_CI_ISOLATED_ROOT) : null;
if (root) {
  function check(value) {
    if (value instanceof URL) value = fileURLToPath(value);
    if (Buffer.isBuffer(value)) value = value.toString();
    if (typeof value !== 'string') return;
    const target = path.resolve(value);
    for (const folder of ['evidence', 'examples', '.local']) {
      const prefix = path.join(root, folder);
      if (target === prefix || target.startsWith(prefix + path.sep))
        throw new Error('Offline CI cannot access historical evidence or private state: ' + folder);
    }
    const name = path.basename(target);
    if (path.dirname(target) === root && /^\.env(?:\.|$)/.test(name) &&
        !['.env.example', '.env.sample', '.env.template'].includes(name))
      throw new Error('Offline CI cannot access private environment files');
  }
  for (const name of ['readFileSync', 'readFile', 'openSync', 'open', 'readdirSync', 'readdir', 'opendirSync', 'opendir']) {
    const original = fs[name];
    fs[name] = function (value, ...args) { check(value); return original.call(this, value, ...args); };
  }
  for (const name of ['readFile', 'open', 'readdir', 'opendir']) {
    const original = fs.promises[name];
    fs.promises[name] = async function (value, ...args) { check(value); return original.call(this, value, ...args); };
  }
  const net = require('node:net');
  const original = net.Socket.prototype.connect;
  net.Socket.prototype.connect = function (...args) {
    const options = typeof args[0] === 'object' ? args[0] : {host: typeof args[1] === 'string' ? args[1] : 'localhost'};
    const host = options.host || 'localhost';
    if (!options.path && !['localhost', '127.0.0.1', '::1'].includes(host))
      throw new Error('Offline CI permits only loopback network connections');
    return original.apply(this, args);
  };
}
