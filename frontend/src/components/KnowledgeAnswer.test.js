import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import KnowledgeAnswer from './KnowledgeAnswer';
let node,root;
beforeEach(()=>{global.IS_REACT_ACT_ENVIRONMENT=true;node=document.createElement('div');document.body.appendChild(node);root=createRoot(node);});
afterEach(()=>{act(()=>root.unmount());node.remove();});
const base={answer:'조건을 확인해 주세요.',answer_status_label:'확인 필요',sources:[],related:[],review_material:[],alternatives:[],confirmations:[]};
test('review material is distinct from answer evidence',()=>{
 const source={id:'r',division:'건축부문',section_no:'6-4-3',section_title:'방수',printed_page:606,pdf_page:662,lines:[{n:1,text:'원문',display:'원문'}],image_url:'/api/source/p662.png'};
 act(()=>root.render(<KnowledgeAnswer result={{...base,review_material:[source]}}/>));
 expect(node.textContent).toContain('확인 필요');expect(node.textContent).toContain('검토용 원문');expect(node.textContent).not.toContain('답변 근거 ·');
 expect(node.querySelector('img').getAttribute('src')).toBe('/api/source/p662.png');
});
test('confirmed citations show original line and source page',()=>{
 const source={id:'s',division:'기계설비부문',section_no:'6-2-2',section_title:'적산열량계',printed_page:680,pdf_page:736,lines:[{n:1,text:'배관공 0.569',display:'배관공 0.569',cited:true}]};
 act(()=>root.render(<KnowledgeAnswer result={{...base,answer_status_label:'답변 확인',answer:'0.569인입니다.',sources:[source]}}/>));
 expect(node.textContent).toContain('답변 확인');expect(node.textContent).toContain('인쇄 680쪽');expect(node.textContent).toContain('배관공 0.569');
});
test('ambiguous numbers show alternatives without values',()=>{
 act(()=>root.render(<KnowledgeAnswer result={{...base,alternatives:[{division:'건축',number:'4-1-1',title:'먹매김'},{division:'토목',number:'4-1-1',title:'다른 절'}]}}/>));
 expect(node.querySelectorAll('li')).toHaveLength(2);expect(node.textContent).toContain('먹매김');
});
