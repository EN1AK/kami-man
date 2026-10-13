// Windows Jihuanshe bridge. Credentials stay inside the mini-program.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');
const readline = require('node:readline');
const {setTimeout: delay} = require('node:timers/promises');

class BridgeError extends Error { constructor(code) {super(code);this.code=code;} }
class Cdp {
  constructor(WebSocket) { this.WebSocket=WebSocket;this.socket=null;this.contexts=new Map();this.pending=new Map();this.sequence=0; }
  close() {if(this.socket)this.socket.terminate();this.socket=null;this.contexts.clear();this.rejectPending();}
  rejectPending() {for(const job of this.pending.values()){clearTimeout(job.timer);job.reject(new BridgeError('session_lost'));}this.pending.clear();}
  async connect() {
    if(this.socket?.readyState===this.WebSocket.OPEN)return;
    this.close();
    const socket=new this.WebSocket('ws://127.0.0.1:62000');this.socket=socket;
    socket.on('message',raw=>{
      if(this.socket!==socket)return;
      let msg;try{msg=JSON.parse(raw.toString());}catch{return;}
      if(msg.method==='Runtime.executionContextCreated')this.contexts.set(msg.params.context.id,msg.params.context);
      if(msg.method==='Runtime.executionContextDestroyed')this.contexts.delete(msg.params.executionContextId);
      if(msg.method==='Runtime.executionContextsCleared')this.contexts.clear();
      const job=this.pending.get(msg.id);
      if(job){clearTimeout(job.timer);this.pending.delete(msg.id);msg.error?job.reject(new BridgeError('context_lost')):job.resolve(msg.result);}
    });
    socket.on('close',()=>{if(this.socket===socket){this.contexts.clear();this.rejectPending();}});
    socket.on('error',()=>{});
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{socket.terminate();reject(new BridgeError('session_lost'));},5000);
      socket.once('open',()=>{clearTimeout(timer);resolve();});
      socket.once('error',()=>{clearTimeout(timer);reject(new BridgeError('session_lost'));});
    });
    await this.refresh();
  }
  call(method,params={}) {
    if(this.socket?.readyState!==this.WebSocket.OPEN)return Promise.reject(new BridgeError('session_lost'));
    return new Promise((resolve,reject)=>{
      const id=++this.sequence;
      const timer=setTimeout(()=>{this.pending.delete(id);reject(new BridgeError('session_lost'));},7000);
      this.pending.set(id,{resolve,reject,timer});
      this.socket.send(JSON.stringify({id,method,params}));
    });
  }
  async refresh(){this.contexts.clear();await this.call('Runtime.disable');await this.call('Runtime.enable');await delay(300);}
  async evaluate(expression,contextId){const result=await this.call('Runtime.evaluate',{expression,contextId,returnByValue:true,silent:true});if(result.exceptionDetails)throw new BridgeError('context_lost');return result.result?.value;}
}

const SCOPES = Object.freeze({
  ygo: {jp:{game_key:'ygo',game_sub_key:'ocg',source_language:'jp'},sc:{game_key:'ygo',game_sub_key:'sc',source_language:'sc'},en:{game_key:'ygo',game_sub_key:'tcg',source_language:'en'}},
  riftbound: {sc:{game_key:'lol',game_sub_key:'default',source_language:'sc'},tc:{game_key:'lol',game_sub_key:'tc',source_language:'tc'},en:{game_key:'lol',game_sub_key:'en',source_language:'en'},kr:{game_key:'lol',game_sub_key:'kr',source_language:'kr'}},
});
function scopeFor(input) {
  const game=input.game??'ygo',language=input.language??(game==='riftbound'?'sc':'jp');
  if(typeof game!=='string'||typeof language!=='string'||!Object.hasOwn(SCOPES,game)||!Object.hasOwn(SCOPES[game],language))throw new BridgeError('invalid_input');
  return {game,language,...SCOPES[game][language]};
}
function queryCode(operation,input,target) {
  const scope=scopeFor(input);
  const params={game_key:scope.game_key,game_sub_key:scope.game_sub_key};
  if(operation==='versions')return `(function(){
    const state=${target}={status:'pending'},scope=${JSON.stringify(scope)};
    require('api/cloud.js').cloudRequest(${JSON.stringify({...params,keyword:input.keyword??input.name_jp,page:input.page,sorting_price_type:'product'})},'getCardVersions','/api/market/card-versions','get',false).then(response=>{
      const body=response.result.data,rows=Array.isArray(body)?body:body.data;
      if(!Array.isArray(rows))throw new Error();
      const entries=rows.filter(r=>!r.language||r.language===scope.source_language).map(r=>({
        id:r.card_version_id||r.id,card_id:r.card_id,object_type:r.card_object_type||'unknown',
        name_jp:r.name_jp||'',name_cn:r.name_cn||'',name_en:r.name_en||'',
        aliases:[r.name_origin,...(r.card_names||[]).map(n=>n.name_value)].filter(v=>typeof v==='string'&&v),
        number:r.number||'',rarity:r.rarity||'',game:scope.game,language:scope.language,source_language:r.language||null,
      }));
      Object.assign(state,{status:'done',entries,last_page:Array.isArray(body)?1:body.last_page||1});
    }).catch(()=>{state.status='upstream_error';});return true;
  })()`;
  return `(function(){
    const state=${target}={status:'pending'},request=require('api/cloud.js').cloudRequest,scope=${JSON.stringify(scope)};
    Promise.all(${JSON.stringify(input.version_ids)}.map(id=>{
      const params={...${JSON.stringify(params)},card_version_id:id};
      return Promise.all([
        request(params,'findCardVersion','/api/market/card-versions/'+id,'get',false),
        request({...params,filter:'1_month'},'getPriceHistory','/api/market/products/price-history','get',false),
      ]).then(results=>{
        const detail=results[0].result.data,history=results[1].result.data;
        if(Number(detail.id)!==id||detail.game_key!==scope.game_key||detail.game_sub_key!==scope.game_sub_key||!Array.isArray(history))throw new Error();
        const points=history.filter(p=>p&&typeof p.date==='string').sort((a,b)=>a.date.localeCompare(b.date)),latest=points.length?points[points.length-1]:null;
        return {id,game:scope.game,language:scope.language,min_price:detail.min_price??null,market_price:latest?latest.price:null,market_date:latest?latest.date:null};
      }).catch(()=>({id,game:scope.game,language:scope.language,error:true}));
    })).then(prices=>{Object.assign(state,{status:'done',prices});}).catch(()=>{state.status='upstream_error';});return true;
  })()`;
}

class Controller {
  constructor(config) {
    this.config={...config,appId:config.appId||'wx64479c83c7630409'};
    const WebSocket=require(path.join(config.debuggerDir,'node_modules/ws'));
    this.cdp=new Cdp(WebSocket);this.contextId=null;this.debugger=null;this.debuggerReady=false;this.tunnel=null;
    this.needsRuntime=false;this.lastBootstrap=0;
    this.tail=Promise.resolve();this.queued=0;this.stopped=false;this.lastOpen=0;this.nextDebugger=0;this.debuggerBackoff=3000;this.nextTunnel=0;this.tunnelBackoff=3000;
    this.state={ready:false,last_error:'needs_miniapp',recoveries:0,debugger_starts:0,tunnel_starts:0};
  }
  log(event){console.log(new Date().toISOString()+' '+event);}
  enqueue(operation) {
    if(this.queued>=4)return Promise.reject(new BridgeError('busy'));
    this.queued++;
    const result=this.tail.then(operation);
    this.tail=result.catch(()=>{}).finally(()=>{this.queued--;});
    return result;
  }
  startTunnel() {
    if(!this.config.sshHost||this.stopped||this.tunnel||Date.now()<this.nextTunnel)return;
    const ssh=this.config.sshExe||path.join(process.env.WINDIR,'System32/OpenSSH/ssh.exe');
    const child=spawn(ssh,['-NT','-o','BatchMode=yes','-o','ConnectTimeout=10','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3','-o','ExitOnForwardFailure=yes','-R','127.0.0.1:8791:127.0.0.1:8791',this.config.sshHost],{windowsHide:true,stdio:['ignore','ignore','pipe']});
    this.tunnel=child;this.state.tunnel_starts++;this.log('tunnel_start');
    child.stderr.on('data',()=>{});
    child.on('error',()=>this.log('tunnel_start_failed'));
    const started=Date.now();
    child.on('close',()=>{if(this.tunnel!==child)return;this.tunnel=null;if(Date.now()-started>60000)this.tunnelBackoff=3000;this.nextTunnel=Date.now()+this.tunnelBackoff;this.tunnelBackoff=Math.min(this.tunnelBackoff*2,60000);this.log('tunnel_disconnected');});
  }
  async ensureDebugger(deadline) {
    if(this.debuggerReady)return;
    if(!this.debugger&&Date.now()>=this.nextDebugger) {
      if(this.needsRuntime){await this.openMiniapp(true);await delay(1500);this.needsRuntime=false;}
      const child=spawn(process.execPath,[path.join(this.config.debuggerDir,'node_modules/ts-node/dist/bin.js'),path.join(this.config.debuggerDir,'src/index.ts')],{cwd:this.config.debuggerDir,windowsHide:true,stdio:['ignore','pipe','pipe']});
      this.debugger=child;this.state.debugger_starts++;
      readline.createInterface({input:child.stdout}).on('line',line=>{if(line.includes('[frida] script loaded')){this.debuggerReady=true;this.debuggerBackoff=3000;this.log('debugger_ready');}});
      readline.createInterface({input:child.stderr}).on('line',line=>{if(line.includes('WeChatAppEx.exe process not found'))this.needsRuntime=true;});child.on('error',()=>this.log('debugger_start_failed'));
      child.on('close',()=>{if(this.debugger!==child)return;this.debugger=null;this.debuggerReady=false;this.contextId=null;this.cdp.close();this.state.ready=false;this.nextDebugger=Date.now()+this.debuggerBackoff;this.debuggerBackoff=Math.min(this.debuggerBackoff*2,120000);this.log('debugger_disconnected');});
    }
    for(let count=0;count<40&&Date.now()<deadline&&!this.debuggerReady&&this.debugger;count++)await delay(250);
    if(!this.debuggerReady)throw new BridgeError('wechat_unavailable');
  }
  async inspectContext() {
    const expression=`(function(){try{const module=typeof require('api/cloud.js').cloudRequest==='function';let appid='';try{appid=wx.getAccountInfoSync().miniProgram.appId;}catch(_){}return {module,loggedIn:module&&Boolean(getApp().globalData.jwt),appid};}catch(_){return {module:false,loggedIn:false};}})()`;
    const ids=this.contextId!==null?[this.contextId,...this.cdp.contexts.keys()]:[...this.cdp.contexts.keys()];
    let loginMissing=false;
    for(const id of new Set(ids)) {
      let status;try{status=await this.cdp.evaluate(expression,id);}catch(error){if(error.code==='session_lost')throw error;continue;}
      if(status?.module&&(!this.config.appId||status.appid===this.config.appId)) {
        if(status.loggedIn){this.contextId=id;return true;}
        loginMissing=true;
      }
    }
    this.contextId=null;if(loginMissing)throw new BridgeError('needs_login');return false;
  }
  async openMiniapp(bootstrap=false) {
    if(this.config.autoOpen!==true)throw new BridgeError('needs_miniapp');
    if(!this.config.shortcut||!fs.existsSync(this.config.shortcut))throw new BridgeError('needs_miniapp');
    if(Date.now()-(bootstrap?this.lastBootstrap:this.lastOpen)<30000)throw new BridgeError('needs_miniapp');
    if(bootstrap){this.lastBootstrap=Date.now();this.log('runtime_start');}
    else{this.lastOpen=Date.now();this.state.recoveries++;this.log('miniapp_recover');}
    await new Promise((resolve,reject)=>{
      const child=spawn('pwsh.exe',['-NoProfile','-NonInteractive','-File',path.join(__dirname,'recover-miniapp.ps1'),'-ShortcutPath',this.config.shortcut,...(bootstrap?['-LaunchOnly']:[])],{windowsHide:true,stdio:'ignore'});
      const timer=setTimeout(()=>{child.kill();reject(new BridgeError('needs_miniapp'));},10000);
      child.on('error',()=>{clearTimeout(timer);reject(new BridgeError('needs_miniapp'));});
      child.on('close',code=>{clearTimeout(timer);code===0?resolve():reject(new BridgeError('needs_miniapp'));});
    });
  }
  async ensureContext(deadline, recover=true) {
    await this.ensureDebugger(deadline);
    try {await this.cdp.connect();if(await this.inspectContext())return;await this.cdp.refresh();if(await this.inspectContext())return;}
    catch(error){if(error.code==='needs_login')throw error;this.cdp.close();}
    if(!recover)throw new BridgeError('needs_miniapp');
    await this.openMiniapp();
    const contextDeadline=Math.min(deadline,Date.now()+20000);
    while(Date.now()<contextDeadline) {
      try{await this.cdp.connect();await this.cdp.refresh();if(await this.inspectContext())return;}
      catch(error){if(error.code==='needs_login')throw error;this.cdp.close();}
      await delay(500);
    }
    throw new BridgeError('needs_miniapp');
  }
  async queryOnce(operation,payload,deadline=Date.now()+75000) {
    const jobName='__kamiJhs_'+crypto.randomBytes(10).toString('hex'),target='globalThis['+JSON.stringify(jobName)+']';
    const contextId=this.contextId,started=Date.now();
    if(started>=deadline)throw new BridgeError('query_timeout');
    try {
      await this.cdp.evaluate(queryCode(operation,payload,target),contextId);
      while(Date.now()-started<30000&&Date.now()<deadline){await delay(200);const result=await this.cdp.evaluate(target,contextId);if(result?.status==='done')return {...result,elapsed_ms:Date.now()-started};if(result?.status==='upstream_error')throw new BridgeError('upstream_error');}
      throw new BridgeError('query_timeout');
    } finally {try{await this.cdp.evaluate('delete '+target,contextId);}catch{}}
  }
  async run(operation,payload,deadline=Date.now()+75000) {
    for(let attempt=0;attempt<2;attempt++) {
      try {
        if(Date.now()>=deadline)throw new BridgeError('query_timeout');
        await this.ensureContext(deadline);this.state.ready=true;this.state.last_error=null;
        if(operation==='probe')return {ready:true};
        if(operation==='versions') {
          const entries=[];let lastPage=1;
          for(let page=1;page<=lastPage;page++){
            const result=await this.queryOnce(operation,{...payload,page},deadline);
            lastPage=Number(result.last_page);if(!Number.isInteger(lastPage)||lastPage<1||lastPage>20)throw new BridgeError('too_many_versions');
            entries.push(...result.entries);
          }
          return {entries,last_page:lastPage};
        }
        const result=await this.queryOnce(operation,payload,deadline);return {prices:result.prices};
      } catch(error) {
        this.state.ready=false;this.state.last_error=error.code||'internal_error';
        if(attempt===0&&Date.now()<deadline&&['session_lost','context_lost','query_timeout'].includes(error.code)){this.contextId=null;this.cdp.close();continue;}
        throw error;
      }
    }
  }
  stop(){this.stopped=true;clearInterval(this.timer);this.cdp.close();this.debugger?.kill();this.tunnel?.kill();}
  start(){this.startTunnel();this.enqueue(()=>this.run('probe',{})).catch(()=>{});this.timer=setInterval(()=>{this.startTunnel();if(this.queued===0&&!this.stopped)this.enqueue(()=>this.run('probe',{})).catch(()=>{});},30000);}
}

function validate(route,body) {
  const {game,language}=scopeFor(body);
  if(route==='/v1/versions') {
    const keyword=body.keyword??body.name_jp;
    if(typeof keyword!=='string'||!keyword.trim()||keyword.length>120)throw new BridgeError('invalid_input');
    return {operation:'versions',payload:{keyword:keyword.trim(),game,language}};
  }
  if(route==='/v1/prices') {
    const ids=body.version_ids;
    if(!Array.isArray(ids)||ids.length<1||ids.length>20||ids.some(id=>!Number.isSafeInteger(id)||id<=0)||new Set(ids).size!==ids.length)throw new BridgeError('invalid_input');
    return {operation:'prices',payload:{version_ids:ids,game,language}};
  }
  throw new BridgeError('not_found');
}
function authenticated(header,token) {const actual=Buffer.from(header||''),expected=Buffer.from('Bearer '+token);return actual.length===expected.length&&crypto.timingSafeEqual(actual,expected);}
function serve(controller,config) {
  return http.createServer(async(req,res)=>{
    const send=(status,body)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(body));};
    if(!authenticated(req.headers.authorization,config.token))return send(401,{error:'unauthorized'});
    if(req.method==='GET'&&req.url==='/health')return send(200,{...controller.state,queued:controller.queued,debugger_pid:controller.debugger?.pid||null,tunnel_pid:controller.tunnel?.pid||null});
    if(req.method!=='POST')return send(404,{error:'not_found'});
    try {
      const chunks=[];let size=0;for await(const chunk of req){size+=chunk.length;if(size>8192)throw new BridgeError('invalid_input');chunks.push(chunk);}
      let body;try{body=JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{throw new BridgeError('invalid_input');}
      if(!body||typeof body!=='object'||Array.isArray(body))throw new BridgeError('invalid_input');
      const {operation,payload}=validate(req.url,body);
      const deadline=Date.now()+75000;
      const result=await controller.enqueue(()=>controller.run(operation,payload,deadline));send(200,result);
    }catch(error){const code=error.code||'internal_error';send(code==='invalid_input'?400:code==='not_found'?404:code==='busy'?429:503,{error:code});}
  });
}
if(require.main===module) {
  const config=JSON.parse(fs.readFileSync(process.env.JHS_CONFIG_FILE||process.argv[2],'utf8').replace(/^\uFEFF/,''));
  if(typeof config.token!=='string'||config.token.length<32)throw new Error('Bridge token must be configured');
  const controller=new Controller(config);const server=serve(controller,config);
  server.listen(8791,'127.0.0.1',()=>{controller.log('bridge_listening');controller.start();});
  const stop=()=>{clearInterval(stopTimer);controller.stop();server.close();setTimeout(()=>process.exit(0),2000).unref();};
  const started=Date.now(),stopFile=path.join(path.dirname(process.env.JHS_CONFIG_FILE||process.argv[2]),'stop.request');
  const stopTimer=setInterval(()=>{try{if(fs.statSync(stopFile).mtimeMs>=started)stop();}catch{}},1000);process.on('SIGINT',stop);process.on('SIGTERM',stop);
}
module.exports={BridgeError,Cdp,Controller,scopeFor,queryCode,validate,authenticated,serve};