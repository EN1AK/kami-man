const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {validate,authenticated,queryCode}=require('./bridge.cjs');

test('reject arbitrary operations, duplicate IDs and oversized requests',()=>{
  for(const [route,body] of [['/eval',{expression:'anything'}],['/v1/prices',{version_ids:[1,1]}],['/v1/prices',{version_ids:[-1]}],['/v1/prices',{version_ids:Array.from({length:21},(_,i)=>i+1)}],['/v1/versions',{name_jp:'x'.repeat(121)}]])assert.throws(()=>validate(route,body));
});
test('authentication requires the complete expected bearer token',()=>{
  assert.equal(authenticated('Bearer abc','abc'),true);
  for(const value of ['', 'abc', 'Bearer ab', 'Bearer abc\n'])assert.equal(authenticated(value,'abc'),false);
});
test('card names are data, even if they contain JavaScript source text',async()=>{
  const name="');globalThis.injected=true;//";let received;
  const context={require:()=>({cloudRequest:async params=>{received=params.keyword;return {result:{data:[]}};}})};
  vm.createContext(context);vm.runInContext(queryCode('versions',{name_jp:name,page:1},'globalThis.result'),context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(received,name);assert.equal(context.injected,undefined);assert.equal(context.result.status,'done');
});

test('HTTP bridge rejects unauthenticated requests and preserves split UTF-8 names',async t=>{
  const http=require('node:http');const {serve}=require('./bridge.cjs');let calls=0;
  const controller={enqueue:async run=>run(),run:async(operation,payload)=>{calls++;return payload;}};
  const server=serve(controller,{token:'test-only-token'});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>server.close(resolve)));
  const body=Buffer.from(JSON.stringify({name_jp:'原石の皇脈'}));
  const request=token=>new Promise((resolve,reject)=>{
    const req=http.request({host:'127.0.0.1',port:server.address().port,path:'/v1/versions',method:'POST',headers:{Authorization:token,'Content-Type':'application/json'}},res=>{
      const chunks=[];res.on('data',chunk=>chunks.push(chunk));res.on('end',()=>resolve({status:res.statusCode,body:JSON.parse(Buffer.concat(chunks).toString())}));
    });req.on('error',reject);
    const split=body.indexOf(Buffer.from('原'))+1;
    req.write(body.subarray(0,split));setTimeout(()=>req.end(body.subarray(split)),20);
  });
  assert.equal((await request('Bearer wrong')).status,401);assert.equal(calls,0);
  const result=await request('Bearer test-only-token');assert.equal(result.status,200);assert.equal(result.body.name_jp,'原石の皇脈');assert.equal(calls,1);
});
