"""Independent unit sampling, with explicit denominators and missing values."""
def mean(values):return sum(values)/len(values) if values else None
def group(units,seeds):
 attempted=[u for u in units if u['status']!='Pending']
 valid=[u for u in units if u['status']=='Finished' or (u['status']=='Failed' and u['record'].get('failure_category')=='agent_failure')]
 solved=[u for u in valid if u['record'].get('verdict')=='AC']
 first=[u for u in valid if u['seed']==seeds[0]]
 usage=[u['record'].get('usage') for u in valid]
 complete=bool(valid) and all(x is not None and x.get('input_tokens') is not None and x.get('output_tokens') is not None for x in usage)
 total=sum(x['input_tokens']+x['output_tokens'] for x in usage) if complete else None
 return {'attempted':len(attempted),'evaluable':len(valid),'excluded':len(attempted)-len(valid),'solved':len(solved),'solve_rate':len(solved)/len(valid) if valid else None,'pass@1':sum(u['record'].get('verdict')=='AC' for u in first)/len(first) if first else None,'pass@1_denominator':len(first),'mean_input_tokens':mean([x['input_tokens'] for x in usage if x and x.get('input_tokens') is not None]),'mean_output_tokens':mean([x['output_tokens'] for x in usage if x and x.get('output_tokens') is not None]),'mean_total_tokens':mean([x['input_tokens']+x['output_tokens'] for x in usage if x and x.get('input_tokens') is not None and x.get('output_tokens') is not None]),'usage_complete':complete,'usage_observed_units':sum(x is not None for x in usage),'mean_tool_calls':mean([u['record']['tool_calls'] for u in valid if u['record'].get('tool_calls') is not None]),'mean_wall_time':mean([u['record']['wall_time_seconds'] for u in valid if u['record'].get('wall_time_seconds') is not None]),'tokens_per_solved_problem':total/len(solved) if total is not None and solved else None}
def summary(experiment):
 m=experiment['manifest'];units=experiment['units']
 return {'protocol':m['protocol'],'groups':[{'model_index':i,'provider':model['provider'],'model':model['model'],**group([u for u in units if u['model_index']==i],m['seeds'])} for i,model in enumerate(m['models'])],'definitions':{'pass@1':'First configured seed per problem/model; independent Agent Run. Excluded first units are not replaced.','solve_rate':'All evaluable independent units; provider, Judge and infrastructure failures excluded. Agent protocol/budget failures count as unsolved.','usage':'Means use available observations; tokens_per_solved_problem is null if any evaluable usage is missing.','iterative':'Reported separately; pass@1 here is first independent Run with iterative feedback, not single-code-attempt pass@1.'}}
