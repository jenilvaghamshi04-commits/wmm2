(function(root){
  const paths={groups:'/tg-groups',pending:'/pending-messages',sent:'/sent-messages',replies:'/replies',templates:'/message-templates',connections:'/settings'};
  function resolve(path,fallback='groups'){return Object.keys(paths).find(k=>paths[k]===path.replace(/\/+$/,''))||(path==='/'?fallback:'groups')}
  root.WMMPageRoutes={paths,resolve};
  if(typeof module==='object'&&module.exports)module.exports=root.WMMPageRoutes;
})(typeof window==='object'?window:globalThis);
