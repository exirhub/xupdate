(() => {
  const articles = {
    clarity: {
      category: "DESIGN / FIELD NOTE 01",
      title: "The quiet value of doing less",
      paragraphs: [
        "A useful tool does not need to explain its ambition at every turn. Often, its best quality is how little stands between a person and the thing they came to do.",
        "That kind of simplicity takes work. It starts with a clear question: what matters in this particular moment? A familiar label, a thoughtful default, or an option removed can make the answer easier to see.",
        "Doing less is not the same as doing too little. A considered constraint makes space for the important parts. The goal is an experience that feels clear because somebody took the time to understand it."
      ]
    },
    open: {
      category: "OPEN SYSTEMS / FIELD NOTE 02",
      title: "Leave room for the next idea",
      paragraphs: [
        "A system is easier to build on when its decisions are understandable. Clear boundaries, useful notes, and a small working example can be more welcoming than a long list of possibilities.",
        "Working in the open is also a habit of thought. It means making room for a question, acknowledging a limitation, and keeping the reasons behind a decision close to the decision itself.",
        "The next person may see an opportunity that we missed. Good foundations give that idea somewhere to begin."
      ]
    },
    attention: {
      category: "PRACTICE / FIELD NOTE 03",
      title: "A little more attention",
      paragraphs: [
        "Digital experiences are made from small moments. A button that says what will happen. A page that works on a narrow screen. A message that explains how to recover when something goes wrong.",
        "None of these details needs to be spectacular. Together, they show that the person using the tool was part of the thinking from the beginning.",
        "A useful practice is to slow down for one ordinary task and follow it from start to finish. Notice where the experience asks for effort. That is often where the next worthwhile improvement is waiting."
      ]
    }
  };
  const dialog = document.querySelector("#article-dialog");
  const close = document.querySelector("#close-article");
  document.querySelectorAll("[data-article]").forEach(button => {
    button.addEventListener("click", () => {
      const article = articles[button.dataset.article];
      if (!article) return;
      document.querySelector("#article-category").textContent = article.category;
      document.querySelector("#article-title").textContent = article.title;
      const body = document.querySelector("#article-body");
      body.replaceChildren(...article.paragraphs.map(text => {
        const paragraph = document.createElement("p");
        paragraph.textContent = text;
        return paragraph;
      }));
      dialog.showModal();
    });
  });
  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", event => {
    if (event.target === dialog) {
      const r = dialog.getBoundingClientRect();
      if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
    }
  });
})();

