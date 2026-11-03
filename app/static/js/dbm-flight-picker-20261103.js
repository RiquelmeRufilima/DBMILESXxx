/* DBMILESX: seleciona a alternativa salva sem alterar cálculo, preço ou bagagens */
(function(){
  'use strict';
  document.querySelectorAll('.dbm-flight-picker').forEach(function(picker){
    picker.addEventListener('click',function(event){event.stopPropagation();});
  });
  document.addEventListener('change',async function(event){
    const radio=event.target.closest('.dbm-flight-picker input[type="radio"]');
    if(!radio || radio.disabled)return;
    const picker=radio.closest('.dbm-flight-picker');
    const group=Array.from(picker.querySelectorAll('input[type="radio"]')).filter(item=>item.name===radio.name);
    const previous=group.find(item=>item !== radio && item.dataset.wasChosen==='true');
    const feedback=picker.querySelector('.dbm-flight-choice-feedback');
    group.forEach(item=>item.disabled=true);
    const form=new FormData();
    form.set('csrf_token',picker.dataset.csrfToken||'');
    form.set('option_index',radio.value);
    form.set('segment_key',radio.dataset.segmentKey||'');
    try{
      const response=await fetch('/calculations/option/'+encodeURIComponent(picker.dataset.quoteId)+'/flight-choice',{
        method:'POST',body:form,credentials:'same-origin',headers:{'Accept':'application/json'}
      });
      const result=await response.json();
      if(!response.ok||!result.ok)throw new Error(result.message||'Falha ao salvar preferência.');
      group.forEach(item=>{
        item.dataset.wasChosen=String(item===radio);
        item.closest('.dbm-flight-choice')?.classList.toggle('is-selected',item===radio);
        const marker=item.closest('.dbm-flight-choice')?.querySelector('.dbm-flight-choice-marker');
        if(marker)marker.textContent=item===radio?'Selecionada':'Escolher';
      });
      if(feedback){feedback.textContent='✓ Horário selecionado e salvo neste cálculo.';feedback.hidden=false;feedback.classList.remove('is-error');}
    }catch(error){
      if(previous)previous.checked=true;else radio.checked=false;
      if(feedback){feedback.textContent=error.message||'Erro ao salvar horário.';feedback.hidden=false;feedback.classList.add('is-error');}
    }finally{group.forEach(item=>item.disabled=false);}
  });
  document.querySelectorAll('.dbm-flight-picker input[type="radio"]:checked').forEach(item=>item.dataset.wasChosen='true');
})();
