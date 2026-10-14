import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import App from './App';

const prefs={default_model:'gemini-3.8-flash',theme:'light',models:['gemini-3.8-flash'],provider_configured:true,providers:{gemini_configured:true,groq_configured:true},fallback_model:'groq:openai/gpt-oss-120b'};
const result={id:42,document_id:9,document_name:'service-terms.txt',document_type:'txt',selected_model:prefs.default_model,status:'complete',overall_priority:'High',summary:'Review the termination and data handling terms before approval.',findings:[{issue:'Broad data access',severity:'High',evidence:'Provider may access all customer records.',explanation:'This scope could expose more information than needed.',recommended_action:'Limit access to the minimum required data.',evidence_verified:true,source_references:['Page 2']}],limitations:['The full agreement should be checked.'],error_message:'',created_at:'2026-10-12T00:00:00Z',completed_at:'2026-10-12T00:01:00Z',classification:{status:'complete',predicted_label:'High',class_scores:{High:0.88,Medium:0.1,Low:0.02},classifier_version:'demo-classifier',review_required:true,review_reasons:['High-priority prediction always requires human review.'],feature_signals:{supporting:[{term:'customer records',contribution:0.2}],opposing:[{term:'limited access',contribution:0.1}]},nearest_examples:[{sample_id:'DG-0007',label:'High',source_type:'synthetic',similarity:0.81}]}};
function setup(initialPath:string, api:(url:string,init?:RequestInit)=>unknown){
  window.history.pushState({},'',initialPath);
  vi.stubGlobal('fetch',vi.fn(async (input:RequestInfo|URL,init?:RequestInit)=>{
    const url=String(input);
    const data=api(url,init);
    return data instanceof Response?data:Response.json(data);
  }));
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
  return render(<QueryClientProvider client={client}><BrowserRouter><App/></BrowserRouter></QueryClientProvider>);
}
beforeEach(()=>{vi.resetAllMocks();document.cookie='';});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

describe('DocuGuard workspace',()=>{
  it('shows a selected TXT upload and extracted preview',async()=>{
    const view=setup('/upload',(url)=>{
      if(url.endsWith('/settings/'))return prefs;
      if(url.endsWith('/documents/preview/'))return {text:'A complete supplier policy with terms about access and handling.',truncated:false};
      return {};
    });
    expect(await screen.findByRole('heading',{name:'New analysis'})).toBeInTheDocument();
    const file=new File(['A complete supplier policy with terms about access and handling.'], 'policy.txt',{type:'text/plain'});
    const input=view.container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!,{target:{files:[file]}});
    expect(await screen.findByText('policy.txt')).toBeInTheDocument();
    await waitFor(()=>expect(screen.getByRole('button',{name:/Extract text preview/})).toBeEnabled());
    fireEvent.click(screen.getByRole('button',{name:/Extract text preview/}));
    expect(await screen.findByText(/A complete supplier policy/)).toBeInTheDocument();
  });

  it('renders analysis priority and source evidence',async()=>{
    setup('/analysis/42',(url)=>{
      if(url.endsWith('/settings/'))return prefs;
      if(url.endsWith('/analyses/42/'))return result;
      return {detail:'not found'};
    });
    expect(await screen.findByRole('heading',{name:'High review priority'})).toBeInTheDocument();
    expect(await screen.findByText('Broad data access')).toBeInTheDocument();
    expect(screen.getByText(/Provider may access all customer records/)).toBeInTheDocument();
    expect(screen.getByText(/Matched extracted source: Page 2/)).toBeInTheDocument();
    expect(screen.getByText('customer records')).toBeInTheDocument();
    expect(screen.getByText(/DG-0007.*similarity 81.0%/)).toBeInTheDocument();
    expect(await screen.findByRole('heading',{name:'High classifier result'})).toBeInTheDocument();
    expect(screen.getByText('Manual review required')).toBeInTheDocument();
    expect(screen.getByText('Classifier: demo-classifier')).toBeInTheDocument();
  });

  it('renders a useful API failure state',async()=>{
    setup('/dashboard',(url)=>{
      if(url.endsWith('/settings/'))return prefs;
      return new Response(JSON.stringify({detail:'Dashboard unavailable right now.'}),{status:503,headers:{'Content-Type':'application/json'}});
    });
    await waitFor(()=>expect(screen.getByText('We couldn’t load this information.')).toBeInTheDocument());
    expect(screen.getByText('Dashboard unavailable right now.')).toBeInTheDocument();
  });

  it('lets a reviewer save a separate human-assessed label',async()=>{
    const item={id:17,document_name:'supplier-terms.txt',file_type:'txt',analysis_id:42,analysis_summary:'Review the supplier data clause.',status:'complete',predicted_label:'High',class_scores:{High:.8,Medium:.15,Low:.05},classifier_version:'candidate-v1',review_reasons:['High-priority prediction always requires human review.'],review_required:true,review_status:'needs_review',review_note:'',final_label:null,review_updated_at:'2026-10-14T00:00:00Z',created_at:'2026-10-13T00:00:00Z'};
    setup('/reviews',(url,init)=>{
      if(url.endsWith('/settings/'))return prefs;
      if(url.includes('/reviews/')&&init?.method==='POST')return item;
      if(url.includes('/reviews/'))return {count:1,next:null,previous:null,results:[item]};
      return {detail:'not found'};
    });
    expect(await screen.findByRole('heading',{name:'Flagged documents'})).toBeInTheDocument();
    expect(await screen.findByText('supplier-terms.txt')).toBeInTheDocument();
    const card=screen.getByRole('article');
    fireEvent.change(within(card).getByLabelText('Review status'),{target:{value:'reviewed'}});
    fireEvent.change(within(card).getByLabelText('Final human-assessed priority'),{target:{value:'Medium'}});
    fireEvent.click(within(card).getByRole('button',{name:'Save decision'}));
    expect(await screen.findByRole('status')).toHaveTextContent('Review decision saved.');
    const post=vi.mocked(fetch).mock.calls.find(([url,init])=>String(url).includes('/reviews/17/decision/')&&init?.method==='POST');
    expect(post).toBeDefined();
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({status:'reviewed',final_label:'Medium'});
  });

  it('renders sealed model metrics and a blocked release gate',async()=>{
    const performance={available:true,model_version:'candidate-v1',evaluated_at_utc:'2026-10-14T00:00:00Z',corpus_approval_mode:'owner_approved_showcase_ai_assisted',showcase_nonproduction:true,promotion_status:'candidate_only',test_support:45,test_class_counts:{Low:15,Medium:15,High:15},class_order:['Low','Medium','High'],scores_calibrated:true,test_metrics:{accuracy:.95,macro_f1:.94,balanced_accuracy:.95,per_class:{Low:{precision:.9,recall:.9,'f1-score':.9,support:15,precision_95_ci:[.7,.98],recall_95_ci:[.7,.98]},Medium:{precision:.9,recall:.9,'f1-score':.9,support:15,precision_95_ci:[.7,.98],recall_95_ci:[.7,.98]},High:{precision:1,recall:1,'f1-score':1,support:15,precision_95_ci:[.8,1],recall_95_ci:[.8,1]}},confusion_matrix:[[14,1,0],[1,14,0],[0,0,15]]},test_calibration:{ece:.103,multiclass_brier:.048,reliability_bins:[{lower:.8,upper:.9,count:10,mean_confidence:.85,accuracy:.8}]},test_review_routing:{total:45,review_count:15,review_rate:.333,auto_clear_count:30,auto_clear_coverage:.667,errors_outside_review_queue:2,auto_clear_error_rate:.067,auto_clear_accuracy:.933},promotion_gate:{status:'blocked',checks:{dual_human_reviewed_corpus:false,minimum_test_support_met:false},blocking_reasons:['dual_human_reviewed_corpus'],criteria:{},automatic_promotion:false},limitations:['Showcase evaluation only.']};
    setup('/model-performance',(url)=>url.endsWith('/settings/')?prefs:performance);
    expect(await screen.findByRole('heading',{name:'Model performance'})).toBeInTheDocument();
    expect(await screen.findByText('Release gate: blocked')).toBeInTheDocument();
    expect(screen.getByText('0.940')).toBeInTheDocument();
    expect(screen.getByText(/15 test examples per class|independent dual human review/i)).toBeInTheDocument();
  });

  it('shows live classifier counts and recent review decisions on the dashboard',async()=>{
    const dashboard={total_documents:4,awaiting_review:1,high_priority:2,manual_review_backlog:3,reviewed_count:5,dismissed_count:1,priority_distribution:[{overall_priority:'High',count:2}],predicted_distribution:[{predicted_label:'High',count:2},{predicted_label:'Low',count:1}],recent_review_decisions:[{classification_id:9,document_name:'privacy-policy.txt',predicted_label:'High',status:'reviewed',final_label:'Medium',note:'Reviewed manually.',updated_at:'2026-10-14T00:00:00Z'}],recent_analyses:[],recent_activity:[]};
    setup('/dashboard',(url)=>url.endsWith('/settings/')?prefs:dashboard);
    expect(await screen.findByRole('heading',{name:'Overview'})).toBeInTheDocument();
    expect(screen.getByText('Manual review backlog')).toBeInTheDocument();
    expect(screen.getByText('Current classifier distribution')).toBeInTheDocument();
    expect(screen.getByText('privacy-policy.txt')).toBeInTheDocument();
    expect(screen.getByText(/human label Medium/)).toBeInTheDocument();
  });
});
