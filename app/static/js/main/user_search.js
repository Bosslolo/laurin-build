// User Search functionality for non-admin mode
class UserSearch {
    constructor() {
        this.searchInput = document.getElementById('userSearch');
        this.clearButton = document.getElementById('clearSearch');
        this.userGrid = document.getElementById('userGrid');
        
        this.init();
    }
    
    getUserCards() {
        // Dynamically get all user cards each time (including newly loaded ones)
        return document.querySelectorAll('.user-card-container');
    }
    
    init() {
        if (!this.searchInput) return;
        
        // Add event listeners
        this.searchInput.addEventListener('input', (e) => this.handleSearch(e.target.value));
        this.searchInput.addEventListener('keydown', (e) => this.handleKeydown(e));
        this.clearButton.addEventListener('click', () => this.clearSearch());
        
        // Initial count
        this.updateResultsCount(this.getUserCards().length);
    }
    
    handleSearch(query) {
        const searchTerm = query.toLowerCase().trim();
        
        if (searchTerm === '') {
            this.showAllCards();
            this.clearButton.style.display = 'none';
            this.toggleNoResultsMessage(false);
        } else {
            this.filterCards(searchTerm);
            this.clearButton.style.display = 'block';
        }
        
        this.updateResultsCount(this.getVisibleCards().length);
    }
    
    filterCards(searchTerm) {
        let visibleCount = 0;
        const userCards = this.getUserCards();
        
        userCards.forEach((card, index) => {
            const userName = card.dataset.userName.toLowerCase();
            const firstName = card.dataset.userFirst.toLowerCase();
            const lastName = card.dataset.userLast.toLowerCase();
            
            // Fuzzy search logic
            const isMatch = this.fuzzyMatch(userName, searchTerm) ||
                           this.fuzzyMatch(firstName, searchTerm) ||
                           this.fuzzyMatch(lastName, searchTerm);
            
            if (isMatch) {
                card.classList.remove('hidden');
                card.style.animationDelay = `${visibleCount * 0.1}s`;
                visibleCount++;
            } else {
                card.classList.add('hidden');
            }
        });
        
        this.toggleNoResultsMessage(visibleCount === 0);
    }
    
    fuzzyMatch(text, pattern) {
        let patternIdx = 0;
        let textIdx = 0;
        
        while (textIdx < text.length && patternIdx < pattern.length) {
            if (text[textIdx] === pattern[patternIdx]) {
                patternIdx++;
            }
            textIdx++;
        }
        
        return patternIdx === pattern.length;
    }
    
    showAllCards() {
        const userCards = this.getUserCards();
        userCards.forEach((card, index) => {
            card.classList.remove('hidden');
            card.style.animationDelay = `${index * 0.1}s`;
        });
    }
    
    getVisibleCards() {
        const userCards = this.getUserCards();
        return Array.from(userCards).filter(card => !card.classList.contains('hidden'));
    }
    
    toggleNoResultsMessage(show) {
        let noResultsMsg = document.getElementById('noResultsMessage');
        
        if (show && !noResultsMsg) {
            noResultsMsg = document.createElement('div');
            noResultsMsg.id = 'noResultsMessage';
            noResultsMsg.className = 'col-12 no-results';
            noResultsMsg.innerHTML = `
                <i class="fas fa-search"></i>
                <h4>No users found</h4>
                <p>Try adjusting your search terms</p>
            `;
            this.userGrid.appendChild(noResultsMsg);
        } else if (!show && noResultsMsg) {
            noResultsMsg.remove();
        }
    }
    
    clearSearch() {
        this.searchInput.value = '';
        this.showAllCards();
        this.clearButton.style.display = 'none';
        this.toggleNoResultsMessage(false);
        this.updateResultsCount(this.getUserCards().length);
        this.searchInput.focus();
    }
    
    updateResultsCount(count) {
        // For user view, we don't show the count since there's no resultsCount element
        // This is just here for compatibility
    }
    
    handleKeydown(e) {
        if (e.key === 'Escape') {
            this.clearSearch();
        }
    }
}

// Initialize search when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    new UserSearch();
});
