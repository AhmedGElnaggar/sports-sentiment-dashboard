#include <iostream>
#include <string>
#include <map>
#include <vector>
#include <fstream>
#include <sqlite3.h>
#include <iomanip>

// Stats we track per league
struct LeagueStats {
    std::string league;
    int total_matches = 0;
    int total_goals = 0;
    int home_wins = 0;
    int away_wins = 0;
    int draws = 0;
};

int main() {
    sqlite3* db;
    int rc = sqlite3_open("sports.db", &db);
    if (rc != SQLITE_OK) {
        std::cerr << "Cannot open database: " << sqlite3_errmsg(db) << std::endl;
        return 1;
    }

    std::map<std::string, LeagueStats> stats;

    // Query finished matches
    const char* sql = "SELECT league, home_score, away_score FROM matches WHERE status = 'FINISHED' AND home_score IS NOT NULL AND away_score IS NOT NULL";
    sqlite3_stmt* stmt;
    sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        std::string league = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        int home = sqlite3_column_int(stmt, 1);
        int away = sqlite3_column_int(stmt, 2);

        auto& s = stats[league];
        s.league = league;
        s.total_matches++;
        s.total_goals += home + away;
        if (home > away) s.home_wins++;
        else if (away > home) s.away_wins++;
        else s.draws++;
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    // Write results to JSON file for Flask to serve
    std::ofstream out("analysis.json");
    out << "[\n";
    bool first = true;
    for (auto& [key, s] : stats) {
        if (!first) out << ",\n";
        first = false;
        double avg_goals = s.total_matches > 0 ? (double)s.total_goals / s.total_matches : 0;
        double home_pct  = s.total_matches > 0 ? (double)s.home_wins / s.total_matches * 100 : 0;
        double away_pct  = s.total_matches > 0 ? (double)s.away_wins / s.total_matches * 100 : 0;
        double draw_pct  = s.total_matches > 0 ? (double)s.draws / s.total_matches * 100 : 0;
        out << "  {\n";
        out << "    \"league\": \"" << s.league << "\",\n";
        out << "    \"total_matches\": " << s.total_matches << ",\n";
        out << "    \"total_goals\": " << s.total_goals << ",\n";
        out << "    \"avg_goals_per_game\": " << std::fixed << std::setprecision(2) << avg_goals << ",\n";
        out << "    \"home_win_pct\": " << std::fixed << std::setprecision(1) << home_pct << ",\n";
        out << "    \"away_win_pct\": " << std::fixed << std::setprecision(1) << away_pct << ",\n";
        out << "    \"draw_pct\": " << std::fixed << std::setprecision(1) << draw_pct << "\n";
        out << "  }";
    }
    out << "\n]";
    out.close();

    std::cout << "Analysis complete. Results saved to analysis.json" << std::endl;
    return 0;
}