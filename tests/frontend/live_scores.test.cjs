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
    {homeAway:'away',team:{id:'17',displayName:'New England Patriots'},score:'3',linescores:[{period:1,value:3},{period:2,value:0}]},
    {homeAway:'home',team:{id:'8',displayName:'Detroit Lions'},score:'14',linescores:[{period:1,value:7},{period:2,value:7}]},
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
