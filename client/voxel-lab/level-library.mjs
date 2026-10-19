// The chooser changes presentation only. Tasks and par values are authored
// menu metadata; choosing a card delegates to the existing game flow.
function append(parent, tag, className, text) {
  const node = (parent.ownerDocument || document).createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  parent.append(node);
  return node;
}

function disclosure(parent, label, className, ariaLabel) {
  const details = append(parent, 'details', className);
  const summary = append(details, 'summary', `${className}-toggle`, label);
  // Native summary supplies keyboard operation, expanded state and focus.
  // Retain usable targets even before the surrounding library CSS loads.
  summary.style.minHeight = '44px';
  summary.style.minWidth = '44px';
  if (ariaLabel) summary.setAttribute('aria-label', ariaLabel);
  const content = append(details, 'div', `${className}-content`);
  return {disclosure: details, summary, content};
}

/** Replace the list with compact cards, preserving the public play labels. */
export function renderLevelCards(list, levels, {
  record, bestStars, energyText, pieceLabel, onChoose, nextUp
}) {
  list.replaceChildren();
  let chapter=null;
  for (const [index, level] of levels.entries()) {
    if(level.onboarding?.chapter!==chapter){
      chapter=level.onboarding?.chapter;
      if(chapter){const heading=append(list,'li','level-chapter');append(heading,'h2','',chapter);}
    }
    const row = record(level.id) || {};
    const stars = Math.max(0, Math.min(3, Math.trunc(Number(bestStars(level.id)) || 0)));
    const next = level === nextUp || level.id === nextUp?.id;
    const item = append(list, 'li', 'level-card');
    item.dataset.level = level.id;
    item.classList.toggle('won', stars > 0);
    item.classList.toggle('next', next);
    const card = append(item, 'button', 'ls-card level-card-main');
    card.type = 'button';
    card.setAttribute('aria-label', `Play level ${index + 1}, ${level.title}`);
    card.addEventListener('click', () => onChoose(level));
    append(card, 'strong', 'level-card-title', level.title);
    if(level.project)append(card,'span','project-step',`Pinball · Step ${level.project.step} of ${level.project.total}`);
    append(card, 'span', 'task-count', `${level.task_count} ${level.task_count === 1 ? 'thing' : 'things'} to do`);
    if(level.onboarding?.estimated_minutes?.length===2){
      const [lo,hi]=level.onboarding.estimated_minutes;
      const estimate=append(card,'span','level-time-estimate',`Est. ${lo}–${hi} min`);
      estimate.title=level.onboarding.estimate_basis;
    }
    const starText = append(card, 'span', 'stars', '★'.repeat(stars) + '☆'.repeat(3 - stars));
    starText.setAttribute('aria-label', `${stars} of 3 stars`);
    if(row.energy_j!=null)append(card,'span','level-card-best',`Best win: ${energyText(row.energy_j)} (par ${energyText(level.par_energy_j)})`);
  }
  return list;
}

/** Append existing return-link, generator and recent controls to .content. */
export function createLevelMoreMenu(parent, {label = 'More', id} = {}) {
  const menu = disclosure(parent, label, 'level-library-more');
  if (id) menu.disclosure.id = id;
  return menu;
}
