// Build fresh server-owned responses using only portable repository fixtures.
const {spawnSync}=require('node:child_process');
const result=spawnSync(process.env.PYTHON || 'python3',['-m','tests.availability_client_fixture'],{
 encoding:'utf8',maxBuffer:16*1024*1024
});
if(result.error)throw result.error;
if(result.status!==0)throw Error(`Availability fixture failed (${result.status}): ${result.stderr}`);
module.exports=JSON.parse(result.stdout);
