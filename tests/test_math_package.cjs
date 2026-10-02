'use strict';
const assert=require('node:assert/strict');
const math=require('../app/dashboard/opportunity_static/math-scenarios.js');
const example=math.example();
assert.equal(example.legs.length,2);assert.equal(example.states.length,3);
const html=math.render({label:'<script>alert(1)</script>',original_outputs:'original',calculation:{states:{'<img>':'-1'},quantities:['1'],reasons:['<svg>'],ev_label:'manual What-if'}});
assert(!html.includes('<script>'));assert(html.includes('&lt;img&gt;'));assert(html.includes('manual What-if'));
assert(math.controls({session:'s~g',hash:'s',cutoff:'x'}).includes('math-download'));
console.log('Math What-if rendering, escaping and example checks pass');
