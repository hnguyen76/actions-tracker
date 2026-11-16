const { test } = require('node:test');
const assert = require('node:assert/strict');
global.window = globalThis;
require('../../src/actions_tracker/templates/static/scoreboard.js');
require('../../src/actions_tracker/templates/static/live-scores.js');
const api = global.ActionsLiveScores;
const event = () => ({
  id:'401873053',date:'2026-11-15T14:30:00Z',
  status:{period:2,displayClock:'5:47',type:{state:'in',completed:false,shortDetail:'5:47 - 2nd'}},
  competitions:[{situation:{possession:'17',possessionText:'NE 39',yardLine:61,shortDownDistanceText:'1st & 10'},competitors:[
    {homeAway:'away',team:{id:'17',displayName:'New England Patriots',color:'123ABC'},score:'3',linescores:[{period:1,value:3},{period:2,value:0}]},
    {homeAway:'home',team:{id:'8',displayName:'Detroit Lions',color:'C8102E'},score:'14',linescores:[{period:1,value:7},{period:2,value:7}]},
  ]}],
});
const game = {game_id:290823,league:'nfl',start_time:'2026-11-15T14:30:00Z',home_name:'Detroit Lions',away_name:'New England Patriots'};

test('official score and situation preserve possession, field label, clock and zero quarter', () => {
  const e=api.parseEvent(event());
  assert.equal(e.state,'live');
  assert.equal(e.away_score,3);
  assert.equal(e.situation.possession,'away');
  assert.equal(e.situation.possession_text,'NE 39');
  assert.equal(e.situation.clock,'5:47');
  assert.deepEqual(e.situation.away_period_scores,[3,0]);
  assert.equal(e.situation.away_color,'#123abc');
  assert.equal(e.situation.home_color,'#c8102e');
});
const driveSummary = (eventId='401873053', side='home') => ({
  header:{id:eventId},
  drives:{current:{
    id:'drive-24',description:'3 plays, 11 yards, 1:28',
    team:{id:side==='home'?'8':'17',abbreviation:side==='home'?'DET':'NE',logos:[{href:'https://a.espncdn.com/i/teamlogos/nfl/500/det.png'}]},
    plays:[{clock:{displayValue:'2:12'},type:{text:'Penalty'},statYardage:-5,
      text:'Illegal Formation, 5 yards, enforced at DET 37 - No Play.',
      end:side==='home'
        ?{down:3,distance:6,yardsToEndzone:68,shortDownDistanceText:'3rd & 6',possessionText:'DET 32'}
        :{down:1,distance:10,yardsToEndzone:61,shortDownDistanceText:'1st & 10',possessionText:'NE 39'},
    }],
  }},
});
test('current drive becomes a normalized field position with the first-down line', () => {
  const e=api.parseEvent(event());
  const home=api.parseDrive(driveSummary(),e,e.event_id);
  assert.equal(home.team_side,'home');
  assert.equal(home.ball_x,68);
  assert.equal(home.first_down_x,62);
  assert.equal(home.down_distance,'3rd & 6');
  assert.equal(home.spot,'DET 32');
  assert.equal(home.play_yards,-5);
  const away=api.parseDrive(driveSummary(e.event_id,'away'),e,e.event_id);
  assert.equal(away.team_side,'away');
  assert.equal(away.ball_x,39);
  assert.equal(away.first_down_x,49);
  const headerOnly=driveSummary();
  headerOnly.header.competitions=[{competitors:[{homeAway:'away',team:{id:'17'}},{homeAway:'home',team:{id:'8'}}]}];
  assert.equal(api.parseDrive(headerOnly,{event_id:e.event_id,situation:null},e.event_id).team_side,'home');
});
test('drive start is the first scrimmage play of the drive, kickoffs left out', () => {
  const e=api.parseEvent(event());
  const home=driveSummary();
  home.drives.current.plays.unshift(
    {type:{text:'Kickoff'},start:{team:{id:'17'},yardsToEndzone:65},end:{yardsToEndzone:75}},
    {type:{text:'Rush'},start:{team:{id:'8'},down:1,distance:10,yardsToEndzone:79},end:{yardsToEndzone:75}});
  assert.equal(api.parseDrive(home,e,e.event_id).start_x,79);
  const away=driveSummary(e.event_id,'away');
  away.drives.current.plays.unshift({type:{text:'Pass Reception'},start:{team:{id:'17'},yardsToEndzone:75},end:{yardsToEndzone:70}});
  assert.equal(api.parseDrive(away,e,e.event_id).start_x,25);
  assert.equal(api.parseDrive(driveSummary(),e,e.event_id).start_x,null);
});
test('big plays come from the last two drives and name the team that gained', () => {
  const e=api.parseEvent(event());
  const play=(id,type,text)=>({id,type:{text:type},text:text||type});
  const summary={header:{id:e.event_id},drives:{
    previous:[
      {team:{id:'8'},plays:[play('8001','Pass Interception Return')]},
      {team:{id:'17'},plays:[play('9000','Rush'),play('9001','Pass Interception Return','Pass intercepted by DET.')]}],
    current:{team:{id:'8'},plays:[play('9101','Fumble Recovery (Own)'),play('9102','Fumble Recovery (Opponent)'),
      play('9103','Blocked Field Goal'),play('9104','Field Goal Missed'),play('9105','Field Goal Good'),
      play('9106','Interception Return Touchdown'),{type:{text:'Field Goal Missed'}}]}}};
  assert.deepEqual(api.parseBigPlays(summary,e,e.event_id),[
    {id:'9001',kind:'interception',side:'home',text:'Pass intercepted by DET.'},
    {id:'9102',kind:'fumble_lost',side:'away',text:'Fumble Recovery (Opponent)'},
    {id:'9103',kind:'field_goal_missed',side:'away',text:'Blocked Field Goal'},
    {id:'9104',kind:'field_goal_missed',side:'away',text:'Field Goal Missed'}]);
  assert.deepEqual(api.parseBigPlays(summary,e,'other'),[]);
});
test('big plays: a return touchdown is left to the score jump; a play listed twice counts once', () => {
  const e=api.parseEvent(event());
  const drive={team:{id:'17'},plays:[
    {id:'9201',type:{text:'Pass Interception Return'},scoringPlay:true,text:'Pass intercepted, returned 40 yards.'},
    {id:'9202',type:{text:'Fumble Recovery (Opponent)'},text:'Fumble recovered by DET, returned for a TOUCHDOWN.'},
    {id:'9203',type:{text:'Pass Interception Return'},text:'Pass intercepted by DET.'}]};
  const summary={header:{id:e.event_id},drives:{previous:[drive],current:drive}};
  assert.deepEqual(api.parseBigPlays(summary,e,e.event_id),[{id:'9203',kind:'interception',side:'home',text:'Pass intercepted by DET.'}]);
});
test('drive parser rejects the wrong event, unknown offense and unusable positions', () => {
  const e=api.parseEvent(event());
  assert.equal(api.parseDrive(driveSummary('other'),e,e.event_id),null);
  const unknown=driveSummary(); unknown.drives.current.team.id='999';
  assert.equal(api.parseDrive(unknown,e,e.event_id),null);
  const bad=driveSummary(); delete bad.drives.current.plays[0].end.yardsToEndzone;
  assert.equal(api.parseDrive(bad,e,e.event_id),null);
});
test('zero score is valid, absent score does not become zero', () => {
  const raw=event(), side=raw.competitions[0].competitors[0];
  side.score='0'; assert.equal(api.parseEvent(raw).away_score,0);
  for (const value of [null,undefined,'',false,'-1','3.5']) { side.score=value; assert.equal(api.parseEvent(raw).away_score,null); }
});
test('pregame and abnormal post states never masquerade as live or final', () => {
  const raw=event(); raw.status.type={state:'pre',completed:false,shortDetail:'Postponed'};
  assert.equal(api.parseEvent(raw).state,'scheduled');
  raw.status.type={state:'post',completed:false,shortDetail:'Canceled'};
  assert.equal(api.parseEvent(raw).state,'scheduled');
  raw.status.type={state:'post',completed:true,shortDetail:'Final'};
  assert.equal(api.parseEvent(raw).state,'final');
});
test('match requires both full teams, orientation, bounded time and an unambiguous event', () => {
  const e=api.parseEvent(event());
  assert.equal(api.matchEvent(game,[e]),e);
  assert.equal(api.matchEvent({...game,away_name:'New England College'},[e]),null);
  assert.equal(api.matchEvent({...game,home_name:game.away_name,away_name:game.home_name},[e]),null);
  assert.equal(api.matchEvent({...game,start_time:'2026-11-16T14:30:00Z'},[e]),null);
  assert.equal(api.matchEvent(game,[e,{...e,event_id:'duplicate'}]),null);
  assert.equal(api.matchEvent({...game,espn_event_id:e.event_id},[e,{...e,event_id:'duplicate'}]),e);
});
test('known college full-name aliases are matched, abbreviations are not guessed', () => {
  const e={...api.parseEvent(event()),home_name:'NC State Wolfpack',away_name:'Miami Hurricanes'};
  assert.equal(api.matchEvent({...game,home_name:'North Carolina State Wolfpack',away_name:'Miami (FL) Hurricanes'},[e]),e);
  assert.equal(api.matchEvent({...game,home_name:'NCST',away_name:'MIA'},[e]),null);
});
test('scoreboard date uses Eastern time through midnight and DST', () => {
  assert.equal(api.dateKey('2026-11-16T02:00:00Z'),'20261115');
  assert.equal(api.dateKey('2026-07-16T03:00:00Z'),'20260715');
});
test('fetch groups games by league/date and returns scores without modifying original games', async () => {
  const calls=[];
  const result=await api.fetchGames([game,{...game,game_id:290824}],async (url,opts) => {
    calls.push({url,opts}); return {ok:true,json:async()=>({events:[event()]})};
  });
  assert.equal(calls.length,1);
  assert.match(calls[0].url,/football\/nfl\/scoreboard\?dates=20261115$/);
  assert.equal(calls[0].opts.credentials,'omit');
  assert.equal(calls[0].opts.cache,'no-store');
  assert.equal(result.scores.length,2);
  assert.equal(result.scores[0].graded,false);
  assert.equal(game.away_score,undefined);
});
test('live football fetches current drive by verified event id and caches it for ten seconds', async () => {
  const target={...game,espn_event_id:'401873053'},calls=[];
  const mock=async (url,opts) => {
    calls.push({url,opts});
    return {ok:true,json:async()=>url.includes('/summary?')?driveSummary():{events:[event()]}};
  };
  const first=await api.fetchGames([target],mock),second=await api.fetchGames([target],mock);
  assert.equal(calls.filter(x=>x.url.includes('/summary?')).length,1);
  assert.equal(first.scores[0].drive.spot,'DET 32');
  assert.equal(second.scores[0].drive.ball_x,68);
  assert.deepEqual(first.scores[0].drive.big_plays,[]);
  const summaryCall=calls.find(x=>x.url.includes('/summary?'));
  assert.equal(summaryCall.opts.credentials,'omit');
  assert.equal(summaryCall.opts.cache,'no-store');
});
test('college request includes all FBS groups; one league failure preserves successful scores', async () => {
  const urls=[];
  const result=await api.fetchGames([game,{...game,game_id:3,league:'ncaaf'}],async url => {
    urls.push(url);
    if(url.includes('college-football')) return {ok:false,status:503};
    return {ok:true,json:async()=>({events:[event()]})};
  });
  assert.ok(urls.some(x=>x.includes('groups=80&limit=300')));
  assert.deepEqual(result.failed,[3]);
  assert.equal(result.scores.length,1);
});
test('offline, malformed data, missing teams and missing scores fail safely', async () => {
  for(const response of [()=>{throw new TypeError('offline');},()=>({ok:true,json:async()=>({})}),()=>({ok:true,json:async()=>({events:[]})}),()=>{
    const raw=event(); raw.competitions[0].competitors[0].score=null;
    return {ok:true,json:async()=>({events:[raw]})};
  }]) {
    const result=await api.fetchGames([game],async()=>response());
    assert.deepEqual(result.failed,[game.game_id]);
    assert.equal(result.scores.length,0);
  }
});

const halfSummary = (id='401873053', wallclock='2026-11-15T16:05:48Z') => ({header:{id,competitions:[{status:{period:2,type:{name:'STATUS_HALFTIME'}}}]},drives:{current:{plays:[{
  type:{id:'65',text:'End of Half'},period:{number:2},clock:{displayValue:'0:00'},wallclock,
}]}}});
const halfNow=Date.parse('2026-11-15T16:12:00Z');
test('halftime ETA uses explicit end-of-half time plus verified league baseline', () => {
  assert.equal(api.halftimeEnd(halfSummary(),game,'401873053',halfNow),'2026-11-15T16:18:48.000Z');
  assert.equal(api.halftimeEnd(halfSummary(),{...game,league:'ncaaf'},'401873053',halfNow),'2026-11-15T16:25:48.000Z');
  assert.equal(api.halftimeEnd(halfSummary(),{...game,league:'nba'},'401873053',halfNow),null);
});
test('halftime ETA is absent without the explicit second-quarter end marker', () => {
  for (const field of ['wallclock','type','period','clock']) {
    const body=halfSummary(); delete body.drives.current.plays[0][field];
    assert.equal(api.halftimeEnd(body,game,'401873053',halfNow),null);
  }
  for (const stamp of ['bad','2026-11-15T16:30:00Z','2026-11-15T13:00:00Z']) {
    assert.equal(api.halftimeEnd(halfSummary('401873053',stamp),game,'401873053',halfNow),null);
  }
});
test('wrong game, final half or already resumed game cannot produce a halftime ETA', () => {
  assert.equal(api.halftimeEnd(halfSummary('other'),game,'401873053',halfNow),null);
  const body=halfSummary(); body.drives.current.plays[0].period.number=4;
  assert.equal(api.halftimeEnd(body,game,'401873053',halfNow),null);
  body.drives.current.plays[0].period.number=2; body.header.competitions[0].status.period=3;
  assert.equal(api.halftimeEnd(body,game,'401873053',halfNow),null);
});
test('duplicate corrected markers use latest timestamp, never the page opening time', () => {
  const body=halfSummary(); body.drives.previous=[{plays:[{...body.drives.current.plays[0],wallclock:'2026-11-15T16:06:00Z'}]}];
  assert.equal(api.halftimeEnd(body,game,'401873053',halfNow),'2026-11-15T16:19:00.000Z');
});
test('regular season halftime fetch is cached per event across score polls', async () => {
  const raw=event(), start=new Date(Date.now()-90*60000).toISOString(), ended=new Date(Date.now()-3*60000).toISOString();
  raw.id='401873054';raw.date=start;raw.season={type:2};raw.status.type={state:'in',name:'STATUS_HALFTIME',shortDetail:'Halftime'};
  raw.status.displayClock='0:00';
  const target={...game,start_time:start,espn_event_id:raw.id},calls=[];
  const mock=async url=>{calls.push(url);return {ok:true,json:async()=>url.includes('/summary?')?halfSummary(raw.id,ended):{events:[raw]}};};
  const first=await api.fetchGames([target],mock),second=await api.fetchGames([target],mock);
  assert.equal(calls.filter(x=>x.includes('/summary?')).length,1);
  assert.equal(first.scores[0].situation.halftime_ends_at,second.scores[0].situation.halftime_ends_at);
  assert.equal(first.scores[0].situation.is_halftime,true);
  assert.equal(first.failed.length,0);
});
test('missing summary does not hide the score or invent a fresh halftime start', async () => {
  const raw=event();raw.id='401873055';raw.season={type:2};raw.status.type={state:'in',name:'STATUS_HALFTIME',shortDetail:'Halftime'};
  const result=await api.fetchGames([game],async url=>url.includes('/summary?')?{ok:false,status:503}:{ok:true,json:async()=>({events:[raw]})});
  assert.equal(result.scores[0].away_score,3);
  assert.equal(result.scores[0].situation.halftime_ends_at,null);
  assert.equal(result.failed.length,0);
});
test('postseason has no generic halftime estimate or summary request', async () => {
  const raw=event();raw.season={type:3};raw.status.type={state:'in',name:'STATUS_HALFTIME',shortDetail:'Halftime'};
  const calls=[];const result=await api.fetchGames([game],async url=>{calls.push(url);return {ok:true,json:async()=>({events:[raw]})};});
  assert.equal(calls.length,1);
  assert.equal(result.scores[0].situation.halftime_ends_at,undefined);
});
