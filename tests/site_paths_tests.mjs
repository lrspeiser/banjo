import test from 'node:test';
import assert from 'node:assert/strict';
import {sitePath} from '../client/voxel-lab/site-paths.mjs';
import {returnURL} from '../client/voxel-lab/anonymous-profile.mjs';

test('test API, navigation and bearer return links cannot default to production routes',()=>{
  for(const path of ['/play','/machine','/api/profile','/api/machine','/api/checkpoint']){
    assert.equal(sitePath('',path),path);
    assert.equal(sitePath('/test',path),'/test'+path);
  }
  const id='77777777-7777-4777-8777-777777777777';
  assert.equal(returnURL('https://banjo.is',id,'/test'),'https://banjo.is/test/play?visitor='+id);
  assert.equal(returnURL('https://banjo.is',id),'https://banjo.is/play?visitor='+id);
  assert.throws(()=>sitePath('/other','/play'));
  assert.throws(()=>sitePath('/test','//other.example/api'));
});
